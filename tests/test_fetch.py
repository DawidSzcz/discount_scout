from datetime import timedelta

import pytest
from django.utils import timezone

from scout.fetch import Outcome, Page, classify, wait_for_slot
from scout.fixtures import load_fixture, scrub
from scout.models import ShopState


@pytest.mark.parametrize(
    "name, expected",
    [
        ("euro_akamai", Outcome.BLOCKED),
        ("komputronik_cloudflare", Outcome.BLOCKED),
        ("asus_403", Outcome.CAPTCHA),  # DataDome device check
        ("electro_challenge", Outcome.CAPTCHA),  # Cloudflare Turnstile
    ],
)
def test_block_pages_are_detected(name, expected):
    assert classify(load_fixture("blocked", name)) == expected


@pytest.mark.parametrize("shop", ["xkom", "neonet", "morele", "deluxury", "techlord", "mediamarkt"])
def test_real_product_pages_are_ok(shop):
    # x-kom/neonet/mediamarkt pages mention "challenge-platform" scripts; that alone must not count as a block.
    assert classify(load_fixture(shop, "product")) == Outcome.OK


@pytest.mark.parametrize(
    "page, expected",
    [
        (Page(url="u", tier=1, status=404), Outcome.NOT_FOUND),
        (Page(url="u", tier=1, status=410), Outcome.NOT_FOUND),
        (Page(url="u", tier=1, status=500), Outcome.HTTP_ERROR),
        (Page(url="u", tier=1, status=429), Outcome.BLOCKED),
        (Page(url="u", tier=1, error="timeout: 30s"), Outcome.TIMEOUT),
        (Page(url="u", tier=1, error="ConnectionError: refused"), Outcome.HTTP_ERROR),
        (Page(url="u", tier=1, status=200, html="<title>Just a moment...</title>"), Outcome.BLOCKED),
        (Page(url="u", tier=1, status=403, html='<div class="cf-turnstile"></div>'), Outcome.CAPTCHA),
    ],
)
def test_classify_generic(page, expected):
    assert classify(page) == expected


def test_scrub_ips_keeps_prices_and_versions():
    html = "IP:<b>198.51.100.23</b> price 13.349,00 jquery 3.2.1 v1.2.3.4.5"
    assert scrub(html) == "IP:<b>203.0.113.1</b> price 13.349,00 jquery 3.2.1 v1.2.3.4.5"


@pytest.mark.django_db
def test_requests_to_same_shop_are_spaced(settings):
    settings.SCOUT_SHOP_GAP_SECONDS = (10, 10)
    slept = []
    assert wait_for_slot("xkom", sleep=slept.append) == 0  # first request: no wait
    assert wait_for_slot("xkom", sleep=slept.append) == pytest.approx(10, abs=1)
    assert wait_for_slot("morele", sleep=slept.append) == 0  # other shops are independent
    assert len(slept) == 1


@pytest.mark.django_db
def test_no_wait_when_gap_already_passed(settings):
    settings.SCOUT_SHOP_GAP_SECONDS = (10, 10)
    ShopState.objects.create(key="xkom", last_request_at=timezone.now() - timedelta(minutes=1))
    assert wait_for_slot("xkom", sleep=lambda s: pytest.fail("should not sleep")) == 0


def test_title_entities_are_decoded():
    assert Page(url="u", tier=1, status=200, html="<title>Laptop 14&quot; &amp; more</title>").title == 'Laptop 14" & more'
