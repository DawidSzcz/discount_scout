from decimal import Decimal

import pytest

from scout.fixtures import load_fixture
from scout.shops import get_shop, shop_for_url
from scout.shops.structured import parse_price

# Expected values read from the saved pages (2026-11-23 probe).
EXPECTED = {
    "xkom": dict(price="13349.00", mpn="UX8407AA-SN515X", in_stock=True, title_has="Zenbook Duo"),
    "neonet": dict(price="13349.00", mpn="UX8407AA-SN515X", in_stock=True, title_has="Zenbook Duo"),
    "morele": dict(price="12321.04", ean="4711636433600", in_stock=True, title_has="UX8407AA-SN129X"),
    "deluxury": dict(price="12498.00", in_stock=True, title_has="UX8407AA-SN515X"),
    "techlord": dict(price="12499.00", mpn="UX8407AA-SN515X", title_has="Zenbook Duo UX8407AA"),
    "mediamarkt": dict(price="3599.00", ean="4711636362313", in_stock=True, title_has="UM3406GA-QD013W"),
}


@pytest.mark.parametrize("shop_key", EXPECTED)
def test_parse_product_page(shop_key):
    exp = EXPECTED[shop_key]
    offers = get_shop(shop_key).parse(load_fixture(shop_key, "product"))
    assert len(offers) == 1, offers
    o = offers[0]
    assert o.price == Decimal(exp["price"])
    assert o.currency == "PLN"
    assert o.condition == "new"
    assert exp["title_has"] in o.title
    if "mpn" in exp:
        assert o.mpn == exp["mpn"]
    if "ean" in exp:
        assert o.ean == exp["ean"]
    if "in_stock" in exp:
        assert o.in_stock is exp["in_stock"]


@pytest.mark.parametrize(
    "url, key",
    [
        ("https://www.x-kom.pl/p/1610557-laptop.html", "xkom"),
        ("https://neonet.pl/p/1610557", "neonet"),
        ("https://www.morele.net/laptop-16224566/", "morele"),
        ("https://deluxury.pl/pl/p/Laptop/41974", "deluxury"),
        ("https://techlord.pl/asus-p-39087.html", "techlord"),
        ("https://mediamarkt.pl/pl/product/_laptop-1502711.html", "mediamarkt"),
        ("https://allegro.pl/produkt/x", None),  # postponed to v2
        ("https://evil-x-kom.pl/p/1", None),  # suffix match must respect the dot
    ],
)
def test_shop_for_url(url, key):
    shop = shop_for_url(url)
    assert (shop.key if shop else None) == key


@pytest.mark.parametrize(
    "raw, expected",
    [
        (13349, "13349.00"),
        (12321.04, "12321.04"),
        ("12499.00", "12499.00"),
        ("12 499,00 zł", "12499.00"),
        ("12.499,00", "12499.00"),
        ("12,499.00", "12499.00"),
        ("3599", "3599.00"),
        ("", None),
        (None, None),
    ],
)
def test_parse_price(raw, expected):
    assert parse_price(raw) == (Decimal(expected) if expected else None)


def test_page_without_product_yields_nothing():
    blocked = load_fixture("blocked", "euro_akamai")
    assert get_shop("xkom").parse(blocked) == []
    assert get_shop("techlord").parse(blocked) == []


# --- tier-2 shops --------------------------------------------------------------------------------

TIER2_EXPECTED = {
    "euro": dict(price="13999.00", ean="4711636635035", seller="RTV EURO AGD", title_has="UX8407AA-SN515X"),
    "mediaexpert": dict(price="13999.00", ean="4711636635035", title_has="UX8407AA-SN515X"),
    "avans": dict(price="11399.00", title_has="UX8407AA-SN129X"),
    "empik": dict(price="12747.96", seller="Electro Pro Shop", title_has="UX8407AA-SN515X"),
}


@pytest.mark.parametrize("shop_key", TIER2_EXPECTED)
def test_parse_tier2_single_offer_pages(shop_key):
    exp = TIER2_EXPECTED[shop_key]
    shop = get_shop(shop_key)
    assert shop.tiers == (2,)
    (o,) = shop.parse(load_fixture(shop_key, "product", tier=2))
    assert o.price == Decimal(exp["price"]) and o.currency == "PLN" and o.condition == "new"
    assert exp["title_has"] in o.title
    assert o.in_stock is True
    if "ean" in exp:
        assert o.ean == exp["ean"]
    if "seller" in exp:
        assert o.seller == exp["seller"]


def test_instalment_promo_price_is_not_taken():
    # Media Expert and Euro also show "W ratach splacisz tylko 12 599,12 zl"; the cash price is 13 999.
    for key in ("mediaexpert", "euro"):
        (o,) = get_shop(key).parse(load_fixture(key, "product", tier=2))
        assert o.price == Decimal("13999.00")


def test_ceneo_lists_all_shop_offers():
    ceneo = get_shop("ceneo")
    assert ceneo.kind == "aggregator"
    offers = ceneo.parse(load_fixture("ceneo", "product", tier=2))
    assert len(offers) == 11  # matches the AggregateOffer offerCount on the page
    cheapest = min(offers, key=lambda o: o.price)
    assert cheapest.price == Decimal("12498.00")
    assert cheapest.seller == "deluxury.pl"
    assert cheapest.seller_url.startswith("https://www.ceneo.pl/Click/Offer/?e=")
    assert "UX8407AA-SN515X" in cheapest.title
    assert {o.seller for o in offers} >= {"x-kom.pl", "euro.com.pl", "allegro.pl", "techlord.pl"}
    assert all(o.condition == "new" for o in offers)


def test_ceneo_challenge_page_counts_as_blocked():
    from scout.fetch import Outcome

    ceneo = get_shop("ceneo")
    assert ceneo.classify(load_fixture("ceneo", "challenge")) == Outcome.BLOCKED
    assert ceneo.classify(load_fixture("ceneo", "product", tier=2)) == Outcome.OK


@pytest.mark.parametrize(
    "title, condition",
    [
        ("Laptop ASUS Zenbook Duo UX8407AA-SN515X 32GB 1TB", "new"),
        ("Laptop ASUS Zenbook Duo - OUTLET", "used"),
        ("Asus Zenbook Duo powystawowy, pelny zestaw", "used"),
        ("ASUS Zenbook Duo uzywany", "used"),
        ("ASUS Zenbook Duo używany", "used"),
        ("ASUS Zenbook Duo odnowiony", "refurbished"),
        ("ASUS Zenbook Duo Refurbished Grade A", "refurbished"),
        ("ASUS Zenbook Duo - 20 RAT 0%! demonstracja wideo", "new"),  # "demonstracja" is not "demo"
    ],
)
def test_condition_from_title(title, condition):
    from scout.shops.tier2 import condition_from_title

    assert condition_from_title(title) == condition


@pytest.mark.parametrize(
    "url, key",
    [
        ("https://www.ceneo.pl/199125559", "ceneo"),
        ("https://www.euro.com.pl/laptopy-i-netbooki/x.bhtml", "euro"),
        ("https://www.mediaexpert.pl/komputery/x", "mediaexpert"),
        ("https://www.avans.pl/komputery/x", "avans"),
        ("https://www.empik.com/asus-zenbook,p1778781306,elektronika-p", "empik"),
        ("https://www.oleole.pl/laptopy/x.bhtml", None),  # v2
    ],
)
def test_shop_for_url_tier2(url, key):
    shop = shop_for_url(url)
    assert (shop.key if shop else None) == key


def test_ceneo_titles_are_unescaped():
    offers = get_shop("ceneo").parse(load_fixture("ceneo", "product", tier=2))
    assert not any("&quot;" in o.title for o in offers)
    assert any('14.0"3K' in o.title for o in offers)
