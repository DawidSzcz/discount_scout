from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from scout.checks import check_offer, due_offers
from scout.fetch import Page
from scout.fixtures import load_fixture
from scout.models import CheckFailure, Offer, PriceObservation, Product, ProductModel, ShopState
from scout.owner import get_owner

XKOM = load_fixture("xkom", "product")  # 13349.00 PLN
BLOCKED = load_fixture("blocked", "euro_akamai")
NOT_FOUND = Page(url="u", tier=1, status=404, html="<title>Nie znaleziono</title>")
NO_PRODUCT = Page(url="u", tier=1, status=200, html="<title>Laptop</title><p>nothing structured</p>")

pytestmark = pytest.mark.django_db


def fake_fetch(*pages_by_tier):
    """Returns pages in order; records the tiers that were requested."""
    pages = list(pages_by_tier)
    calls = []

    def fetch(url, shop_key, tier):
        calls.append(tier)
        return replace(pages.pop(0), tier=tier)

    fetch.calls = calls
    return fetch


@pytest.fixture
def offer():
    product = Product.objects.create(user=get_owner(), name="Zenbook Duo")
    model = ProductModel.objects.create(product=product, code="UX8407AA-SN515X")
    return Offer.objects.create(model=model, shop="xkom", url="https://www.x-kom.pl/p/1610557")


def test_success_records_price_and_schedules_next(offer):
    now = timezone.now()
    obs = check_offer(offer, fetch_fn=fake_fetch(XKOM), now=now)
    assert obs.price == Decimal("13349.00") and obs.tier_used == 1 and not obs.suspicious
    offer.refresh_from_db()
    assert offer.status == Offer.Status.OK and offer.consecutive_failures == 0
    # default interval 4h +/-20%
    assert timedelta(hours=3.2) <= offer.next_check_at - now <= timedelta(hours=4.8)
    assert ShopState.objects.get(key="xkom").preferred_tier == 1


def test_blocked_tier1_falls_back_to_tier2(offer):
    fetch = fake_fetch(BLOCKED, XKOM)
    obs = check_offer(offer, fetch_fn=fetch)
    assert fetch.calls == [1, 2]
    assert obs.tier_used == 2
    failure = CheckFailure.objects.get()
    assert (failure.reason, failure.tier, failure.http_status) == ("blocked", 1, 403)
    assert ShopState.objects.get(key="xkom").preferred_tier == 2


def test_preferred_tier_is_used_first_then_expires(offer):
    ShopState.objects.create(key="xkom", preferred_tier=2, last_success_at=timezone.now())
    fetch = fake_fetch(XKOM)
    check_offer(offer, fetch_fn=fetch)
    assert fetch.calls == [2]

    ShopState.objects.filter(key="xkom").update(last_success_at=timezone.now() - timedelta(days=2))
    fetch = fake_fetch(XKOM)
    check_offer(offer, fetch_fn=fetch)
    assert fetch.calls == [1]


def test_404_marks_offer_gone_and_stops(offer):
    fetch = fake_fetch(NOT_FOUND)
    assert check_offer(offer, fetch_fn=fetch) is None
    assert fetch.calls == [1]
    offer.refresh_from_db()
    assert offer.status == Offer.Status.GONE
    assert not due_offers(timezone.now() + timedelta(days=30)).filter(pk=offer.pk).exists()


def test_repeated_failures_mark_offer_broken(offer):
    for expected in [Offer.Status.BLOCKED, Offer.Status.BLOCKED, Offer.Status.BROKEN]:
        assert check_offer(offer, fetch_fn=fake_fetch(BLOCKED, BLOCKED)) is None
        offer.refresh_from_db()
        assert offer.status == expected
    assert offer.consecutive_failures == 3
    assert CheckFailure.objects.count() == 6  # 2 tiers x 3 runs
    # one success resets it
    check_offer(offer, fetch_fn=fake_fetch(XKOM))
    offer.refresh_from_db()
    assert (offer.status, offer.consecutive_failures) == (Offer.Status.OK, 0)


def test_parse_error_saves_snapshot(offer, settings):
    check_offer(offer, fetch_fn=fake_fetch(NO_PRODUCT, NO_PRODUCT))
    failures = list(CheckFailure.objects.order_by("tier"))
    assert [f.reason for f in failures] == ["parse_error", "parse_error"]
    assert "snapshot:" in failures[0].detail and settings.SCOUT_VAR_DIR in failures[0].detail


def _observe(offer, price, days_ago, suspicious=False):
    return PriceObservation.objects.create(
        offer=offer, price=Decimal(price), tier_used=1, suspicious=suspicious,
        fetched_at=timezone.now() - timedelta(days=days_ago),
    )


def test_outlier_is_flagged_suspicious(offer):
    for d in (3, 2, 1):
        _observe(offer, "30000.00", d)  # recent median 30000; 13349 is -55%
    obs = check_offer(offer, fetch_fn=fake_fetch(XKOM))
    assert obs.suspicious
    offer.refresh_from_db()
    assert offer.status == Offer.Status.SUSPICIOUS


def test_consistent_outliers_are_accepted_as_real(offer):
    for d in (5, 4, 3):
        _observe(offer, "30000.00", d)
    _observe(offer, "13300.00", 2, suspicious=True)
    _observe(offer, "13400.00", 1, suspicious=True)
    obs = check_offer(offer, fetch_fn=fake_fetch(XKOM))
    assert not obs.suspicious


def test_due_offers_respects_schedule_and_pausing(offer):
    now = timezone.now()
    offer.next_check_at = now + timedelta(hours=1)
    offer.save()
    assert not due_offers(now).exists()
    assert due_offers(now + timedelta(hours=2)).get() == offer  # overdue after downtime: due once
    offer.active = False
    offer.save()
    assert not due_offers(now + timedelta(hours=2)).exists()


def test_aggregator_check_keeps_cheapest_new_offer_with_seller(offer):
    offer.shop, offer.kind, offer.url = "ceneo", Offer.Kind.AGGREGATOR, "https://www.ceneo.pl/199125559"
    offer.save()
    fetch = fake_fetch(load_fixture("ceneo", "product", tier=2))
    obs = check_offer(offer, fetch_fn=fetch)
    assert fetch.calls == [2]  # Ceneo skips tier 1
    assert obs.price == Decimal("12498.00")
    assert obs.seller == "deluxury.pl"
    assert obs.seller_url.startswith("https://www.ceneo.pl/Click/Offer/")
