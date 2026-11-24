"""Discovery for the add-product wizard (PLAN.md section 4).

Stage 1, models: Ceneo search -> group hits into variants (Gemini, or regex fallback).
Stage 2, offers: for each chosen variant, open its Ceneo listing(s) first. The listing itself is
  an offer candidate (its price is the cheapest new offer across ALL shops on Ceneo). For each
  supported shop in the listing, follow Ceneo's "go to shop" link to get the real product URL and
  verify the page (parse + model matching).
  Fallback: every supported shop that Ceneo did not lead to is searched directly with the model
  code (Shop.search_url); the top results are verified the same way.

Note: each followed Ceneo link counts as a paid click for the shop. We only follow links to
supported shops, once per shop per discovery.
"""

import logging
import re
from decimal import Decimal
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from selectolax.lexbor import LexborHTMLParser

from . import llm
from .fetch import Outcome, polite_fetch
from .matching import NO, UNSURE, YES, match, norm
from .shops import all_shops, get_shop, shop_for_url
from .shops.structured import parse_price

log = logging.getLogger(__name__)

CENEO_SEARCH = "https://www.ceneo.pl/;szukaj-{q}"
TRACKING_PARAMS = re.compile(r"^(utm_|ceneo|gclid|fbclid|_ga|ref$|referrer|aff|partner)", re.I)
# Model-code-like tokens: letters and digits with a dash, e.g. UX8407AA-SN515X, CLC108-GNU1-S
CODE_TOKEN = re.compile(r"\b(?=[A-Z0-9-]*\d)(?=[A-Z0-9-]*[A-Z])[A-Z0-9]{3,}(?:-[A-Z0-9]{1,}){1,3}\b")


class DiscoveryError(Exception):
    pass


def _noop(msg):
    log.info(msg)


# --- stage 1: models -----------------------------------------------------------------------------


def parse_ceneo_search(html: str) -> list[dict]:
    """Search result rows that have a Ceneo product page (rows linking straight to a shop are
    single offers without a listing, so they are skipped)."""
    hits, seen = [], set()
    for row in LexborHTMLParser(html).css("div.cat-prod-row"):
        pid = row.attributes.get("data-pid") or row.attributes.get("data-productid")
        if not pid or pid in seen:
            continue
        name_node = row.css_first(".cat-prod-row__name")
        link = row.css_first(f'a[href="/{pid}"]')
        if not name_node or not link:
            continue
        seen.add(pid)
        price = parse_price(row.attributes.get("data-price"))
        hits.append({
            "pid": pid,
            "name": name_node.text(strip=True),
            "price": str(price) if price is not None else "",
            "url": f"https://www.ceneo.pl/{pid}",
        })
    return hits


def group_models_by_code(hits: list[dict]) -> list[dict]:
    """Fallback without Gemini: one variant per model code found in the hit names."""
    groups: dict[str, dict] = {}
    for h in hits:
        tokens = CODE_TOKEN.findall(h["name"].upper())
        if not tokens:
            continue
        code = max(tokens, key=len)
        g = groups.setdefault(norm(code), {"code": code, "description": "", "ceneo_ids": []})
        g["ceneo_ids"].append(h["pid"])
        if not g["description"]:
            g["description"] = h["name"][:120]
    return list(groups.values())


def search_models(query: str, fetch=polite_fetch, progress=_noop) -> list[dict]:
    ceneo = get_shop("ceneo")
    url = CENEO_SEARCH.format(q=quote(query.strip().replace(" ", "+"), safe="+"))
    progress(f"Searching Ceneo for \"{query}\"...")
    page = fetch(url, ceneo.key, 2)
    if ceneo.classify(page) != Outcome.OK:
        raise DiscoveryError(f"Ceneo search failed ({page.status or page.error}). Try again later or add models by hand.")
    hits = parse_ceneo_search(page.html)
    progress(f"Ceneo returned {len(hits)} products.")
    if not hits:
        return []
    models = None
    if llm.available():
        progress("Asking Gemini to pick the variants and merge duplicates...")
        try:
            models = llm.group_models(query, hits)
        except llm.LLMError as e:
            progress(f"Gemini unavailable ({e}); grouping by model code instead.")
    if models is None:
        models = group_models_by_code(hits)
    by_pid = {h["pid"]: h for h in hits}
    for m in models:
        prices = [Decimal(by_pid[i]["price"]) for i in m["ceneo_ids"] if by_pid[i]["price"]]
        m["min_price"] = str(min(prices)) if prices else ""
        m["names"] = [by_pid[i]["name"] for i in m["ceneo_ids"]]
    models.sort(key=lambda m: (m["min_price"] == "", Decimal(m["min_price"] or 0)))
    progress(f"Found {len(models)} variant(s).")
    return models


# --- stage 2: offers -----------------------------------------------------------------------------


def clean_url(url: str) -> str:
    """Drop what Ceneo's redirect adds: tracking parameters (utm_*, ceneo_cid...), the fragment, and
    for shops whose product URLs need no query, the whole query (Euro adds from=ceneo&p=<price>&t=<time>,
    which would make the URL different on every visit)."""
    parts = urlsplit(url)
    shop = shop_for_url(url)
    if shop is not None and not shop.url_needs_query:
        query = ""
    else:
        query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                           if not TRACKING_PARAMS.match(k)])
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def _verdict(code: str, description: str, offer_data, use_llm: bool) -> tuple[str, str]:
    m = match(code, "", offer_data.title, offer_data.sku, offer_data.mpn, offer_data.ean)
    if m.verdict != UNSURE or not use_llm:
        return m.verdict, m.reason
    try:
        same, reason = llm.judge_same_model(code, description, offer_data.title)
    except llm.LLMError:
        return m.verdict, m.reason
    if same is None:
        return UNSURE, f"Gemini unsure: {reason}"
    return (YES if same else NO), f"Gemini: {reason}"


def _verify(shop, page, code, description, use_llm, cand: dict) -> dict:
    """Fill verdict/reason/price/title of a candidate from the shop's own product page."""
    if shop.classify(page) != Outcome.OK:
        return {**cand, "verdict": UNSURE,
                "reason": f"{shop.name} page blocked, could not verify" + (f"; Ceneo says {cand['price']} zł" if cand["price"] else "")}
    parsed = [p for p in shop.parse(page) if p.condition == "new"]
    if not parsed:
        return {**cand, "verdict": UNSURE, "reason": "no price found on the shop page"}
    p = min(parsed, key=lambda x: x.price)
    verdict, reason = _verdict(code, description, p, use_llm)
    return {**cand, "price": str(p.price), "title": p.title or cand["title"], "verdict": verdict, "reason": reason}


def _fetch_ok(shop, url, fetch):
    """Fetch along the shop's tier ladder; the first page that is not blocked, else the last one."""
    page = None
    for tier in shop.tiers:
        page = fetch(url, shop.key, tier)
        if shop.classify(page) in (Outcome.OK, Outcome.NOT_FOUND):
            break
    return page


def search_shop(shop, code, description, fetch=polite_fetch, progress=_noop, use_llm=False) -> list[dict]:
    """Fallback: search one shop for the model code and verify the top results. Returns at most one
    candidate: the first confirmed match, else the first result that could not be ruled out.
    Results that are other models are dropped."""
    progress(f"{code}: searching {shop.name}...")
    page = _fetch_ok(shop, shop.search_page_url(code), fetch)
    if shop.classify(page) != Outcome.OK:
        progress(f"{code}: {shop.name} search failed ({page.status or page.error}).")
        return []
    links = shop.search_links(page, code)
    if not links:
        progress(f"{code}: {shop.name} has no results.")
        return []
    unsure = None
    for url in links:
        final = clean_url(url)
        if final == clean_url(page.final_url or ""):
            product_page = page  # the search redirected straight to the product page
        else:
            product_page = _fetch_ok(shop, final, fetch)
        cand = {"shop": shop.key, "url": final, "price": "", "seller": "", "title": "", "source": "search"}
        cand = _verify(shop, product_page, code, description, use_llm, cand)
        cand["reason"] = f"found by {shop.name} search; {cand['reason']}"
        if cand["verdict"] == YES:
            progress(f"{code}: {shop.name} {cand['price']} zł (yes).")
            return [cand]
        if cand["verdict"] == UNSURE and unsure is None:
            unsure = cand
    if unsure:
        progress(f"{code}: {shop.name} {unsure['price'] or '?'} zł (unsure).")
        return [unsure]
    progress(f"{code}: {shop.name} results are other models.")
    return []


def find_offers(model: dict, fetch=polite_fetch, progress=_noop) -> list[dict]:
    """Offer candidates for one variant: its Ceneo listing(s) + verified supported-shop pages,
    then shop searches for the supported shops Ceneo did not lead to."""
    ceneo = get_shop("ceneo")
    code, description = model["code"], model.get("description", "")
    use_llm = llm.available()
    candidates, seen_shops, seen_urls = [], set(), set()

    for pid in model.get("ceneo_ids", []):
        listing_url = f"https://www.ceneo.pl/{pid}"
        progress(f"{code}: opening Ceneo listing {pid}...")
        page = fetch(listing_url, ceneo.key, 2)
        if ceneo.classify(page) != Outcome.OK:
            progress(f"{code}: Ceneo listing {pid} blocked, skipped.")
            continue
        offers = [o for o in ceneo.parse(page) if o.condition == "new"]
        offers = [o for o in offers if match(code, "", o.title).verdict != NO]
        if not offers:
            progress(f"{code}: no matching new offers on listing {pid}.")
            continue
        best = min(offers, key=lambda o: o.price)
        listing_match = match(code, "", page.title)
        candidates.append({
            "shop": "ceneo", "url": listing_url, "price": str(best.price), "seller": best.seller,
            "title": page.title, "verdict": listing_match.verdict if listing_match.verdict != UNSURE else YES,
            "reason": f"Ceneo listing, {len(offers)} shops, cheapest at {best.seller}",
            "offer_count": len(offers), "source": "ceneo",
        })
        seen_urls.add(listing_url)

        for o in sorted(offers, key=lambda o: o.price):
            shop = shop_for_url(f"https://{o.seller}/")
            if not shop or shop.key == "ceneo" or shop.key in seen_shops or not o.seller_url:
                continue
            seen_shops.add(shop.key)
            progress(f"{code}: following Ceneo link to {shop.name}...")
            shop_page = fetch(o.seller_url, ceneo.key, 2)  # the browser follows the redirect to the shop
            final = clean_url(shop_page.final_url or "")
            if shop_for_url(final) is not shop:
                progress(f"{code}: {shop.name} link did not reach the shop ({shop_page.status or shop_page.error}).")
                seen_shops.discard(shop.key)  # let the shop search try instead
                continue
            if final in seen_urls:
                continue
            seen_urls.add(final)
            cand = {"shop": shop.key, "url": final, "price": str(o.price), "seller": "", "title": o.title, "source": "ceneo"}
            cand = _verify(shop, shop_page, code, description, use_llm, cand)
            candidates.append(cand)
            progress(f"{code}: {shop.name} {cand['price']} zł ({cand['verdict']}).")

    missing = [s for s in all_shops() if s.kind == "single" and s.search_url and s.key not in seen_shops]
    if missing:
        progress(f"{code}: Ceneo did not lead to {len(missing)} supported shop(s); searching them directly.")
    for shop in missing:
        for cand in search_shop(shop, code, description, fetch, progress, use_llm):
            if cand["url"] not in seen_urls:
                seen_urls.add(cand["url"])
                candidates.append(cand)
    return candidates
