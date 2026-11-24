from dataclasses import replace

import pytest

from scout import llm
from scout.discovery import (
    DiscoveryError, clean_url, find_offers, group_models_by_code, parse_ceneo_search, search_models, search_shop,
)
from scout.fetch import Page
from scout.fixtures import load_fixture
from scout.matching import NO, UNSURE, YES
from scout.shops import get_shop

SEARCH = load_fixture("ceneo", "search_zenbook_duo", tier=2)
LISTING = load_fixture("ceneo", "product", tier=2)


def test_parse_ceneo_search_keeps_only_rows_with_a_listing():
    hits = {h["pid"]: h for h in parse_ceneo_search(SEARCH.html)}
    assert {"199125559", "199125553", "194868430", "194868429"} <= hits.keys()
    assert hits["199125559"]["price"] == "12498.00"
    assert hits["199125559"]["url"] == "https://www.ceneo.pl/199125559"
    assert "UX8407AA-SN169X" in hits["192979667"]["name"]  # title links to a shop, but the row has a listing too
    assert not any(h["pid"] in ("193403259", "189836037") for h in hits.values())  # ads / recommendations


def test_group_by_code_merges_duplicate_listings_and_drops_codeless_hits():
    models = {m["code"]: m for m in group_models_by_code(parse_ceneo_search(SEARCH.html))}
    assert sorted(models["UX8407AA-SN515X"]["ceneo_ids"]) == ["199125553", "199125559"]
    assert sorted(models["UX8407AA-SN129X"]["ceneo_ids"]) == ["194868429", "194868430"]
    assert not any("C41N1901" in c for c in models)  # batteries have no dashed model code


def test_search_models_without_gemini():
    models = search_models("zenbook duo", fetch=lambda url, key, tier: SEARCH)
    sn515x = next(m for m in models if m["code"] == "UX8407AA-SN515X")
    assert sn515x["min_price"] == "12498.00"
    assert len(sn515x["names"]) == 2


def test_search_models_with_gemini(settings, monkeypatch):
    settings.GEMINI_API_KEY = "test"
    monkeypatch.setattr(llm, "generate_json", lambda prompt, timeout=60: {"models": [
        {"code": "ux8407aa-sn515x", "description": "Ultra X9, 32GB, 1TB", "ceneo_ids": ["199125559", "199125553", "999"]},
        {"code": "UX8407AA-SN129X", "description": "Ultra 7, 32GB, 1TB", "ceneo_ids": ["194868430"]},
    ]})
    models = search_models("zenbook duo", fetch=lambda url, key, tier: SEARCH)
    assert [m["code"] for m in models] == ["UX8407AA-SN129X", "UX8407AA-SN515X"]  # cheapest first
    assert models[1]["ceneo_ids"] == ["199125559", "199125553"]  # unknown id 999 dropped


def test_search_models_falls_back_when_gemini_fails(settings, monkeypatch):
    settings.GEMINI_API_KEY = "test"

    def boom(*a, **kw):
        raise llm.LLMError("HTTP 429")

    monkeypatch.setattr(llm, "generate_json", boom)
    log = []
    models = search_models("zenbook duo", fetch=lambda url, key, tier: SEARCH, progress=log.append)
    assert any(m["code"] == "UX8407AA-SN515X" for m in models)
    assert any("Gemini unavailable" in line for line in log)


def test_search_blocked_raises():
    with pytest.raises(DiscoveryError):
        search_models("zenbook duo", fetch=lambda url, key, tier: load_fixture("ceneo", "challenge"))


def test_clean_url():
    assert clean_url("https://techlord.pl/asus-p-39087.html?utm_source=ceneo&utm_medium=referral&ceneo_cid=1a4f#x") \
        == "https://techlord.pl/asus-p-39087.html"
    assert clean_url("https://shop.pl/p?id=5&utm_source=ceneo") == "https://shop.pl/p?id=5"  # unknown shop: keep id
    euro = ("https://www.euro.com.pl/laptopy-i-netbooki/asus-laptop-asus-zd-14-32-1-w11p-touch.bhtml"
            "?from=ceneo&p=13999.00&cr=0&t=20261124-0624&utm_source=ceneo&ceneo_cid=3dda")
    assert clean_url(euro) == "https://www.euro.com.pl/laptopy-i-netbooki/asus-laptop-asus-zd-14-32-1-w11p-touch.bhtml"


def test_redirect_links_are_recognised():
    from scout.fetch.fetchers import is_redirect_link

    assert is_redirect_link("https://www.ceneo.pl/Click/Offer/?e=abc")
    assert is_redirect_link("https://redirect.ceneo.pl/offers/181252104/10772?e=x")
    assert not is_redirect_link("https://www.ceneo.pl/199125559")
    assert not is_redirect_link("https://www.x-kom.pl/Click/x")


SHOP_PAGES = {  # seller on Ceneo -> (fixture, final URL after Ceneo's redirect)
    "deluxury.pl": ("deluxury", "https://deluxury.pl/pl/p/Laptop/41974?utm_source=ceneo"),
    "techlord.pl": ("techlord", "https://techlord.pl/asus-p-39087.html?ceneo_cid=x"),
    "x-kom.pl": ("xkom", "https://www.x-kom.pl/p/1610557.html"),
    "neonet.pl": ("neonet", "https://www.neonet.pl/p/1610557.html"),
    "avans.pl": ("avans", "https://www.avans.pl/laptop-sn129x"),  # fixture is the SN129X page
    "euro.com.pl": ("euro", "https://www.euro.com.pl/laptop.bhtml"),
}


NOT_FOUND = Page(url="u", tier=1, status=404, html="<title>Nie znaleziono</title>")


def listing_fetch():
    """Ceneo listing + redirects to shop pages; shop searches find nothing (404)."""
    redirects = {o.seller_url: o.seller for o in get_shop("ceneo").parse(LISTING)}
    calls = []

    def fetch(url, key, tier):
        calls.append((key, url))
        if url == "https://www.ceneo.pl/199125559":
            return LISTING
        if key != "ceneo":
            return NOT_FOUND
        fixture, final = SHOP_PAGES[redirects[url]]
        return replace(load_fixture(fixture, "product", tier=2), final_url=final)

    fetch.calls = calls
    return fetch


def test_find_offers_follows_links_only_for_supported_shops():
    fetch = listing_fetch()
    model = {"code": "UX8407AA-SN515X", "description": "", "ceneo_ids": ["199125559"]}
    cands = {c["shop"]: c for c in find_offers(model, fetch=fetch)}

    listing = cands["ceneo"]
    assert listing["price"] == "12498.00" and listing["seller"] == "deluxury.pl" and listing["verdict"] == YES

    assert set(cands) == {"ceneo", "deluxury", "techlord", "xkom", "neonet", "avans", "euro"}
    ceneo_calls = [u for k, u in fetch.calls if k == "ceneo"]
    assert len(ceneo_calls) == 1 + 6  # listing + one link per supported shop; allegro, sferis, octacom... never
    # Supported shops Ceneo did not lead to are searched directly, the others are not.
    assert {k for k, u in fetch.calls if k != "ceneo"} == {"morele", "mediamarkt", "mediaexpert", "empik"}
    assert cands["techlord"]["url"] == "https://techlord.pl/asus-p-39087.html"  # tracking params removed
    for shop in ("deluxury", "techlord", "xkom", "neonet", "euro"):
        assert cands[shop]["verdict"] == YES, shop
    assert cands["avans"]["verdict"] == NO and "SN129X" in cands["avans"]["reason"]


def test_find_offers_uses_gemini_for_unclear_pages(settings, monkeypatch):
    settings.GEMINI_API_KEY = "test"
    monkeypatch.setattr(llm, "judge_same_model", lambda code, desc, title: (True, "specs match"))
    # strip the code from x-kom's page so the deterministic matcher is unsure
    fetch = listing_fetch()

    def fetch_without_code(url, key, tier):
        page = fetch(url, key, tier)
        return replace(page, html=page.html.replace("UX8407AA-SN515X", "")) if "x-kom" in page.final_url else page

    cands = {c["shop"]: c for c in find_offers(
        {"code": "UX8407AA-SN515X", "description": "Ultra X9", "ceneo_ids": ["199125559"]}, fetch=fetch_without_code)}
    assert cands["xkom"]["verdict"] == YES and cands["xkom"]["reason"] == "Gemini: specs match"


CODE = "UX8407AA-SN515X"
REDIRECTING_SEARCH = {  # exact-code search lands on the product page
    "mediaexpert": "https://www.mediaexpert.pl/laptopy/laptop-asus-zenbook-duo-ux8407aa-sn515x-14-oled",
    "empik": "https://www.empik.com/asus-zenbook-duo-oled-ux8407aa-sn515x-ultra-x9,p1778781306,elektronika-p",
}


def shop_search_fetch():
    """Shop searches from fixtures; every result link opens that shop's product fixture.
    (morele, mediamarkt and avans product fixtures are OTHER models, so their results get dropped.)"""
    calls = []

    def fetch(url, key, tier):
        calls.append((key, url))
        shop = get_shop(key)
        if url == shop.search_page_url(CODE):
            if key in REDIRECTING_SEARCH:
                return replace(load_fixture(key, "product", tier=tier), url=url, final_url=REDIRECTING_SEARCH[key])
            return replace(load_fixture(key, "search_sn515x", tier=tier), url=url, final_url=url)
        return replace(load_fixture(key, "product", tier=tier), url=url, final_url=url)

    fetch.calls = calls
    return fetch


@pytest.mark.parametrize("key, expected", [
    ("xkom", "https://www.x-kom.pl/p/1610557-"),
    ("neonet", "https://www.neonet.pl/p/1610557-"),
    ("morele", "https://www.morele.net/laptop-asus-zenbook-duo-oled-ux8407-ultra-x9-378h-32-gb-1-tb-w11-pro-144-hz-ux8407aa-sn515x-"),
    ("deluxury", "https://deluxury.pl/pl/p/Laptop-Asus-ZenBook-Duo-OLED-UX8407AA-SN515X-"),
    ("techlord", "https://techlord.pl/asus-zenbook-duo-ux8407aa-ultra-x9-378h32gb1tbw11p-oled-144hz-dotyk-p-39087"),
    ("mediamarkt", "https://mediamarkt.pl/pl/product/_laptop-asus-zenbook-duo-oled-ux8407aa-sn515x-"),
    ("euro", "https://www.euro.com.pl/laptopy-i-netbooki/asus-laptop-asus-zd-14-32-1-w11p-touch.bhtml"),
    ("avans", "https://www.avans.pl/komputery-i-tablety/laptopy-i-ultrabooki/laptopy/laptop-asus-zenbook-duo-ux8407aa-sn515x-"),
])
def test_search_result_links(key, expected):
    shop = get_shop(key)
    url = shop.search_page_url(CODE)
    links = shop.search_links(replace(load_fixture(key, "search_sn515x"), url=url, final_url=url), CODE)
    assert links and links[0].startswith(expected)
    assert len(links) <= shop.search_max_results


def test_search_redirect_to_product_page_is_the_result():
    shop = get_shop("mediaexpert")
    url = shop.search_page_url(CODE)
    page = replace(load_fixture("mediaexpert", "product"), url=url, final_url=REDIRECTING_SEARCH["mediaexpert"] + "#x")
    assert shop.search_links(page, CODE) == [REDIRECTING_SEARCH["mediaexpert"]]


def test_find_offers_falls_back_to_shop_search_without_ceneo():
    fetch = shop_search_fetch()
    cands = find_offers({"code": CODE, "description": "", "ceneo_ids": []}, fetch=fetch)
    by_shop = {c["shop"]: c for c in cands}
    assert len(cands) == len(by_shop)  # at most one candidate per shop
    assert {k for k, c in by_shop.items() if c["verdict"] == YES} == {
        "xkom", "neonet", "deluxury", "techlord", "euro", "mediaexpert", "empik"}
    # MediaMarkt's fixture is a Zenbook 14 the matcher cannot rule out: shown as unsure, once.
    # Morele and Avans fixtures are sibling variants: dropped.
    assert by_shop["mediamarkt"]["verdict"] == UNSURE
    assert "morele" not in by_shop and "avans" not in by_shop
    assert all(c["source"] == "search" for c in cands)
    assert by_shop["xkom"]["price"] == "13349.00"
    assert by_shop["xkom"]["reason"].startswith("found by x-kom search")
    assert by_shop["mediaexpert"]["url"] == REDIRECTING_SEARCH["mediaexpert"]
    assert [k for k, u in fetch.calls if k == "mediaexpert"] == ["mediaexpert"]  # redirect page reused, not refetched
    assert not any(k == "ceneo" for k, u in fetch.calls)


def test_search_shop_drops_other_models_and_stops_at_first_match():
    fetch = shop_search_fetch()
    log = []
    assert search_shop(get_shop("avans"), CODE, "", fetch, log.append) == []  # both results open the SN129X page
    assert "results are other models" in log[-1]
    assert search_shop(get_shop("deluxury"), CODE, "", fetch)[0]["verdict"] == YES


def test_llm_group_models_rejects_unknown_ids(settings, monkeypatch):
    settings.GEMINI_API_KEY = "test"
    monkeypatch.setattr(llm, "generate_json", lambda prompt, timeout=60: {"models": [{"code": "X-1", "ceneo_ids": ["nope"]}]})
    with pytest.raises(llm.LLMError):
        llm.group_models("q", [{"pid": "1", "name": "n", "price": "1"}])


def test_llm_unavailable_without_key():
    assert not llm.available()
    with pytest.raises(llm.LLMError):
        llm.generate_json("hi")
