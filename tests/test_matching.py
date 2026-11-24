from decimal import Decimal
from types import SimpleNamespace

import pytest

from scout.fixtures import load_fixture
from scout.matching import NO, UNSURE, YES, match, sibling_variant
from scout.shops import get_shop

CODE = "UX8407AA-SN515X"


@pytest.mark.parametrize(
    "kw, verdict",
    [
        (dict(title="Laptop ASUS Zenbook Duo UX8407AA-SN515X 14 OLED"), YES),
        (dict(title="Laptop Asus Zenbook Duo (UX8407AASN515X)"), YES),  # Ceneo strips the dash
        (dict(title="asus zenbook duo ux8407aa sn515x"), YES),
        (dict(title="ASUS Zenbook Duo Ultra X9", mpn="UX8407AA-SN515X"), YES),  # x-kom: code only in mpn
        (dict(title="ASUS Zenbook Duo UX8407AA Ultra X9", sku="UX8407AA-SN515X"), YES),  # TechLord
        (dict(title="Laptop ASUS ZenBook DUO UX8407AA-SN129X 14 OLED"), NO),  # sibling variant
        (dict(title="Asus Zenbook Duo UX8407AASN169X"), NO),
        (dict(title="ASUS Zenbook Duo UX8407AA Ultra X9-378H/32GB/1TB"), UNSURE),  # base only, no suffix
        (dict(title="ASUS Zenbook Duo Ultra X9 378H/32GB/1TB/Win11P OLED"), UNSURE),
    ],
)
def test_match_by_code(kw, verdict):
    assert match(CODE, "", **kw).verdict == verdict


def test_match_by_ean():
    assert match(CODE, "4711636635035", title="Zenbook", offer_ean="4711636635035").verdict == YES
    m = match(CODE, "4711636635035", title="Zenbook", offer_ean="4711636433600")
    assert m.verdict == NO and "EAN" in m.reason


def test_code_beats_ean_mismatch():
    # Some shops put the wrong EAN on the right product; an exact code is stronger evidence.
    assert match(CODE, "4711636635035", title=CODE, offer_ean="1").verdict == YES


def test_sibling_variant_needs_same_shape():
    assert sibling_variant(CODE, "UX8407AA-SN129X") == "UX8407AA-SN129X"
    assert sibling_variant(CODE, "UX8407AA ULTRAX9 378H") is None  # 'ULTRAX' is not a variant suffix
    assert sibling_variant("ZENBOOK14", "ZENBOOK14 OLED") is None  # no base-suffix structure


def test_real_pages():
    model = SimpleNamespace(code=CODE, ean="")
    from scout.matching import match_offer

    for shop in ("xkom", "neonet", "deluxury", "techlord"):
        (o,) = get_shop(shop).parse(load_fixture(shop, "product"))
        assert match_offer(model, o).verdict == YES, shop
    (o,) = get_shop("avans").parse(load_fixture("avans", "product", tier=2))  # the SN129X page
    assert match_offer(model, o).verdict == NO
    ceneo = get_shop("ceneo").parse(load_fixture("ceneo", "product", tier=2))
    verdicts = {o.seller: match_offer(model, o).verdict for o in ceneo}
    assert verdicts["deluxury.pl"] == YES and verdicts["x-kom.pl"] == UNSURE and NO not in verdicts.values()
