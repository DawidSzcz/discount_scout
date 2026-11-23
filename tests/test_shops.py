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
