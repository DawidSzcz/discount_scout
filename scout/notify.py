"""Emails (PLAN.md section 7).

Alert:   a model's price drops below its all-time low (suspicious prices excluded).
Summary: every summary_interval_hours: best current price per model + problems; skipped when
         nothing changed and there are no problems.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from django.conf import settings as django_settings
from django.core.mail import send_mail
from django.db.models import Min
from django.utils import timezone

from .models import CheckFailure, MatchReview, Offer, PriceObservation, ProductModel, Settings
from .shops import get_shop

log = logging.getLogger(__name__)
SIGNATURE = "\n-- \ndiscount_scout"


def fmt_price(price: Decimal, currency: str = "PLN") -> str:
    """12499.5 -> '12 499,50 zł' (Polish style, plain ASCII spaces)."""
    whole, frac = f"{price:,.2f}".split(".")
    return f"{whole.replace(',', ' ')},{frac} {'zł' if currency == 'PLN' else currency}"


def fmt_time(dt: datetime) -> str:
    return timezone.localtime(dt).strftime("%Y-%m-%d %H:%M")


def shop_name(offer: Offer) -> str:
    try:
        return get_shop(offer.shop).name
    except KeyError:
        return offer.shop


def offer_link(obs: PriceObservation) -> str:
    return obs.seller_url or obs.offer.url


def where(obs: PriceObservation) -> str:
    name = shop_name(obs.offer)
    return f"{name} (seller: {obs.seller})" if obs.seller else name


def recipient(cfg: Settings) -> str:
    return cfg.notify_email or django_settings.SCOUT_NOTIFY_EMAIL


def _send(cfg: Settings, subject: str, body: str) -> bool:
    to = recipient(cfg)
    if not to:
        log.warning("no notify email configured; not sending %r", subject)
        return False
    send_mail(subject, body + SIGNATURE, None, [to])
    return True


# --- alert ---------------------------------------------------------------------------------------


def maybe_alert(obs: PriceObservation) -> bool:
    """Email if this observation is a new all-time low for its model. Returns True if sent."""
    if obs.suspicious:
        return False
    model = obs.offer.model
    previous_low = (
        PriceObservation.objects.filter(offer__model=model, suspicious=False, currency=obs.currency)
        .exclude(pk=obs.pk)
        .aggregate(low=Min("price"))["low"]
    )
    if previous_low is None or obs.price >= previous_low:
        return False  # first price ever is a baseline, not a drop
    cfg, _ = Settings.objects.get_or_create(user=model.product.user)
    drop = previous_low - obs.price
    subject = f"New low: {model.code} {fmt_price(obs.price, obs.currency)} at {shop_name(obs.offer)}"
    body = (
        f"New all-time low for {model.product.name} / {model.code}\n\n"
        f"  {fmt_price(obs.price, obs.currency)}  at {where(obs)}\n"
        f"  previous low: {fmt_price(previous_low, obs.currency)} "
        f"(-{fmt_price(drop, obs.currency)}, -{drop / previous_low * 100:.1f}%)\n"
        f"  {offer_link(obs)}\n"
    )
    return _send(cfg, subject, body)


# --- summary -------------------------------------------------------------------------------------


@dataclass
class Summary:
    since: datetime | None
    best: dict = field(default_factory=dict)  # ProductModel -> PriceObservation | None
    failures: list = field(default_factory=list)  # (offer, reason, count, last_at)
    bad_offers: list = field(default_factory=list)  # Offer with status broken/gone/blocked
    suspicious: list = field(default_factory=list)  # PriceObservation
    pending_reviews: int = 0
    changed: bool = False

    @property
    def has_problems(self) -> bool:
        return bool(self.failures or self.bad_offers or self.suspicious or self.pending_reviews)


def latest_valid(offer: Offer) -> PriceObservation | None:
    return offer.observations.filter(suspicious=False).select_related("offer").first()


def collect_summary(cfg: Settings) -> Summary:
    user, since = cfg.user, cfg.last_summary_at
    s = Summary(since=since)
    models = ProductModel.objects.filter(active=True, product__user=user, product__active=True).select_related("product")
    for model in models.order_by("product__name", "code"):
        latest = [o for o in (latest_valid(x) for x in model.offers.filter(active=True)) if o]
        s.best[model] = min(latest, key=lambda o: o.price) if latest else None

    offers = Offer.objects.filter(model__product__user=user, active=True)
    grouped = defaultdict(lambda: [0, None])
    for f in CheckFailure.objects.filter(offer__in=offers, reported=False).select_related("offer__model"):
        g = grouped[(f.offer, f.reason)]
        g[0] += 1
        g[1] = max(g[1], f.at) if g[1] else f.at
    s.failures = sorted(((o, r, n, at) for (o, r), (n, at) in grouped.items()), key=lambda x: x[3], reverse=True)
    s.bad_offers = list(
        offers.filter(status__in=[Offer.Status.BROKEN, Offer.Status.GONE, Offer.Status.BLOCKED]).select_related("model")
    )
    new_obs = PriceObservation.objects.filter(offer__in=offers).select_related("offer__model")
    if since:
        new_obs = new_obs.filter(fetched_at__gt=since)
    s.suspicious = [o for o in new_obs if o.suspicious]
    s.pending_reviews = MatchReview.objects.filter(offer__in=offers, decision__isnull=True).count()
    s.changed = _prices_changed([o for o in new_obs if not o.suspicious], first_summary=since is None)
    return s


def _prices_changed(new_obs, first_summary: bool) -> bool:
    if first_summary:
        return bool(new_obs)
    for obs in new_obs:
        prev = (
            obs.offer.observations.filter(suspicious=False, fetched_at__lt=obs.fetched_at)
            .values_list("price", flat=True)
            .first()
        )
        if prev is None or prev != obs.price:
            return True
    return False


def render_summary(s: Summary) -> tuple[str, str]:
    lines = [f"discount_scout summary{f' (since {fmt_time(s.since)})' if s.since else ''}", ""]
    lines.append("BEST PRICES")
    product = None
    for model, obs in s.best.items():
        if model.product != product:
            product = model.product
            lines.append(f"{product.name}")
        if obs:
            lines.append(f"  {model.code}: {fmt_price(obs.price, obs.currency)} at {where(obs)}")
            lines.append(f"    {offer_link(obs)}")
        else:
            lines.append(f"  {model.code}: no price yet")
    if not s.best:
        lines.append("  (nothing observed yet)")

    if s.has_problems:
        lines += ["", "PROBLEMS"]
    if s.failures:
        lines.append("Failed checks:")
        for offer, reason, count, at in s.failures:
            lines.append(f"  {offer.model.code} @ {shop_name(offer)}: {reason} x{count} (last {fmt_time(at)})")
            lines.append(f"    {offer.url}")
    if s.bad_offers:
        lines.append("Offers needing attention:")
        for offer in s.bad_offers:
            lines.append(f"  {offer.model.code} @ {shop_name(offer)}: {offer.status}")
            lines.append(f"    {offer.url}")
    if s.suspicious:
        lines.append("Suspicious prices held back (not used for alerts):")
        for obs in s.suspicious:
            lines.append(f"  {obs.offer.model.code} @ {shop_name(obs.offer)}: {fmt_price(obs.price, obs.currency)} "
                         f"({fmt_time(obs.fetched_at)})")
    if s.pending_reviews:
        lines.append(f"Matches needing review: {s.pending_reviews}")

    problems = " + problems" if s.has_problems else ""
    return f"discount_scout summary{problems}", "\n".join(lines) + "\n"


def send_summary(cfg: Settings, force: bool = False, now=None) -> bool:
    """Send the summary unless there is nothing to say. Returns True if an email went out."""
    now = now or timezone.now()
    s = collect_summary(cfg)
    sent = False
    if force or s.changed or s.has_problems:
        subject, body = render_summary(s)
        sent = _send(cfg, subject, body)
        if sent:
            CheckFailure.objects.filter(offer__model__product__user=cfg.user, reported=False).update(reported=True)
    else:
        log.info("summary for %s skipped: nothing changed", cfg.user)
    cfg.last_summary_at = now
    cfg.save(update_fields=["last_summary_at"])
    return sent


def summary_due(cfg: Settings, now=None) -> bool:
    now = now or timezone.now()
    return cfg.last_summary_at is None or (now - cfg.last_summary_at).total_seconds() >= cfg.summary_interval_hours * 3600
