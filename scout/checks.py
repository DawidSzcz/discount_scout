"""Checking one offer: fetch along the tier ladder, parse, guard against bad parses, record the
result and schedule the next check (PLAN.md section 6)."""

import gzip
import logging
import random
import statistics
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from .fetch import Outcome, polite_fetch
from .models import CheckFailure, Offer, PriceObservation, Settings, ShopState
from .shops import get_shop

log = logging.getLogger(__name__)

JITTER = 0.2  # +/-20% on the check interval
PREFERRED_TIER_TTL = timedelta(hours=24)  # after this, start from tier 1 again
MEDIAN_WINDOW = timedelta(days=30)
CONFIRM_REPEATS = 2  # this many earlier suspicious prices close to the new one confirm it is real
CONFIRM_TOLERANCE = Decimal("0.05")

FAILURE_REASON = {
    Outcome.BLOCKED: CheckFailure.Reason.BLOCKED,
    Outcome.CAPTCHA: CheckFailure.Reason.CAPTCHA,
    Outcome.HTTP_ERROR: CheckFailure.Reason.HTTP_ERROR,
    Outcome.TIMEOUT: CheckFailure.Reason.TIMEOUT,
    Outcome.NOT_FOUND: CheckFailure.Reason.NOT_FOUND,
}


def due_offers(now=None):
    now = now or timezone.now()
    return (
        Offer.objects.filter(active=True, next_check_at__lte=now, model__active=True, model__product__active=True)
        .exclude(status=Offer.Status.GONE)
        .order_by("next_check_at")
    )


def _ladder(shop, state: ShopState, now) -> list[int]:
    tiers = list(shop.tiers)
    fresh = state.last_success_at and now - state.last_success_at < PREFERRED_TIER_TTL
    if fresh and state.preferred_tier in tiers:
        return tiers[tiers.index(state.preferred_tier):]
    return tiers


def _schedule_next(offer: Offer, cfg: Settings, now):
    hours = cfg.check_interval_hours * random.uniform(1 - JITTER, 1 + JITTER)
    offer.next_check_at = now + timedelta(hours=hours)
    offer.last_checked_at = now


def _save_snapshot(offer: Offer, page) -> str:
    d = Path(settings.SCOUT_VAR_DIR) / "snapshots"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"offer{offer.pk}-tier{page.tier}-{page.fetched_at:%Y%m%d-%H%M%S}.html.gz"
    path.write_bytes(gzip.compress(page.html.encode()))
    return str(path)


def is_suspicious(offer: Offer, price: Decimal, cfg: Settings, now) -> bool:
    """Outlier guard: price far from the model's recent median is held back (e.g. an instalment
    price parsed instead of the full price). Repeated, consistent "outliers" are accepted as real."""
    recent = list(
        PriceObservation.objects.filter(
            offer__model=offer.model, suspicious=False, fetched_at__gte=now - MEDIAN_WINDOW
        ).values_list("price", flat=True)[:200]
    )
    if not recent:
        return False
    median = Decimal(statistics.median(recent))
    if abs(price - median) / median * 100 <= cfg.outlier_pct:
        return False
    last = list(offer.observations.order_by("-fetched_at")[:CONFIRM_REPEATS])
    confirmed = len(last) == CONFIRM_REPEATS and all(
        o.suspicious and abs(o.price - price) / price <= CONFIRM_TOLERANCE for o in last
    )
    return not confirmed


def check_offer(offer: Offer, fetch_fn=polite_fetch, now=None) -> PriceObservation | None:
    """Run one check. Returns the new observation, or None if every tier failed."""
    now = now or timezone.now()
    shop = get_shop(offer.shop)
    cfg, _ = Settings.objects.get_or_create(user=offer.model.product.user)
    state, _ = ShopState.objects.get_or_create(key=shop.key)
    failures = []

    def fail(reason, tier, page=None, detail=""):
        failures.append(CheckFailure(
            offer=offer, at=now, reason=reason, tier=tier,
            http_status=page.status if page else None, detail=detail[:2000],
        ))

    observation = None
    for tier in _ladder(shop, state, now):
        page = fetch_fn(offer.url, shop.key, tier)
        outcome = shop.classify(page)
        if outcome == Outcome.NOT_FOUND:
            fail(CheckFailure.Reason.NOT_FOUND, tier, page)
            offer.status = Offer.Status.GONE
            break
        if outcome != Outcome.OK:
            fail(FAILURE_REASON[outcome], tier, page, page.error or page.title)
            continue
        parsed = shop.parse(page)
        candidates = [o for o in parsed if o.condition == "new"]
        if not candidates:
            reason = CheckFailure.Reason.NO_MATCH if parsed else CheckFailure.Reason.PARSE_ERROR
            fail(reason, tier, page, f"snapshot: {_save_snapshot(offer, page)}")
            continue
        best = min(candidates, key=lambda o: o.price)
        suspicious = is_suspicious(offer, best.price, cfg, now)
        observation = PriceObservation.objects.create(
            offer=offer, fetched_at=now, price=best.price, currency=best.currency,
            seller=best.seller, seller_url=best.seller_url, condition=best.condition,
            in_stock=best.in_stock, tier_used=tier, suspicious=suspicious,
        )
        offer.status = Offer.Status.SUSPICIOUS if suspicious else Offer.Status.OK
        offer.consecutive_failures = 0
        state.preferred_tier, state.last_success_at = tier, now
        state.save(update_fields=["preferred_tier", "last_success_at"])
        break

    CheckFailure.objects.bulk_create(failures)
    if observation is None and offer.status != Offer.Status.GONE:
        offer.consecutive_failures += 1
        if offer.consecutive_failures >= cfg.broken_after_failures:
            offer.status = Offer.Status.BROKEN
        elif any(f.reason in (CheckFailure.Reason.BLOCKED, CheckFailure.Reason.CAPTCHA) for f in failures):
            offer.status = Offer.Status.BLOCKED
    _schedule_next(offer, cfg, now)
    offer.save()
    log.info("checked %s: %s", offer, observation or f"failed ({', '.join(f.reason for f in failures)})")
    return observation
