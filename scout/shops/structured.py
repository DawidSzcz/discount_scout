"""Reusable parsers for schema.org data: JSON-LD (most shops) and microdata (e.g. TechLord)."""

import json
import re
from decimal import Decimal, InvalidOperation

from selectolax.lexbor import LexborHTMLParser

from .base import OfferData, Shop

# --- value helpers -------------------------------------------------------------------------------


def parse_price(value) -> Decimal | None:
    """13349 / 12321.04 / "12 499,00" / "12.499,00 zł" / "12499.00" -> Decimal."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value)).quantize(Decimal("0.01"))
    s = re.sub(r"[^\d,.]", "", str(value))
    if not s:
        return None
    if "," in s and "." in s:  # thousands separator is whichever comes first
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return Decimal(s).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def _schema_suffix(value) -> str:
    return str(value or "").rstrip("/").rsplit("/", 1)[-1].lower()


CONDITIONS = {"newcondition": "new", "usedcondition": "used", "damagedcondition": "used",
              "refurbishedcondition": "refurbished"}
IN_STOCK = {"instock", "limitedavailability", "onlineonly", "instoreonly"}
OUT_OF_STOCK = {"outofstock", "soldout", "discontinued", "preorder", "backorder", "presale"}


def parse_condition(value) -> str:
    return CONDITIONS.get(_schema_suffix(value), "new" if not value else "unknown")


def parse_availability(value) -> bool | None:
    v = _schema_suffix(value)
    return True if v in IN_STOCK else False if v in OUT_OF_STOCK else None


def _types(node: dict) -> set[str]:
    t = node.get("@type", [])
    return {_schema_suffix(x) for x in (t if isinstance(t, list) else [t])}


# --- JSON-LD -------------------------------------------------------------------------------------


def _deep_merge(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        out[k] = _deep_merge(out[k], v) if isinstance(out.get(k), dict) and isinstance(v, dict) else v
    return out


def jsonld_nodes(html: str) -> list[dict]:
    """All top-level JSON-LD nodes. Nodes sharing an @id are merged, because some shop platforms
    (e.g. Shoper, used by Deluxury) split one Product across many <script> blocks."""
    nodes, by_id = [], {}
    for script in LexborHTMLParser(html).css('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.text())
        except (json.JSONDecodeError, TypeError):
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            node_id = item.get("@id")
            if node_id and node_id in by_id:
                by_id[node_id].update(_deep_merge(by_id[node_id], item))
            else:
                if node_id:
                    by_id[node_id] = item
                nodes.append(item)
    return nodes


def find_products(nodes) -> list[dict]:
    """Product nodes anywhere in the tree (e.g. MediaMarkt nests it in BuyAction.object)."""
    found = []

    def walk(x):
        if isinstance(x, dict):
            if "product" in _types(x):
                found.append(x)
                return  # don't descend: nested products are accessories/related items
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(nodes)
    return found


def offer_price(offer: dict) -> Decimal | None:
    price = parse_price(offer.get("price")) or parse_price(offer.get("lowPrice"))
    if price is None:  # some shops only fill priceSpecification
        specs = offer.get("priceSpecification") or []
        for spec in specs if isinstance(specs, list) else [specs]:
            if isinstance(spec, dict) and "strikethrough" not in str(spec.get("priceType", "")).lower():
                price = parse_price(spec.get("price"))
                if price is not None:
                    break
    return price


def product_offers(product: dict) -> list[OfferData]:
    offers = product.get("offers") or []
    offers = offers if isinstance(offers, list) else [offers]
    ean = str(product.get("gtin13") or product.get("gtin") or product.get("gtin14") or "")
    out = []
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        price = offer_price(offer)
        if price is None or price <= 0:
            continue
        seller = offer.get("seller") or {}
        out.append(OfferData(
            price=price,
            currency=str(offer.get("priceCurrency") or "PLN"),
            title=str(product.get("name") or ""),
            sku=str(product.get("sku") or product.get("productID") or ""),
            mpn=str(product.get("mpn") or ""),
            ean=ean,
            seller=seller.get("name", "") if isinstance(seller, dict) else "",
            condition=parse_condition(offer.get("itemCondition") or product.get("itemCondition")),
            in_stock=parse_availability(offer.get("availability")),
        ))
    return out


class JsonLdShop(Shop):
    """Shop whose product page carries a schema.org Product with Offer(s) in JSON-LD."""

    def parse(self, page):
        return [o for p in find_products(jsonld_nodes(page.html)) for o in product_offers(p)]


# --- microdata -----------------------------------------------------------------------------------


class MicrodataShop(Shop):
    """Shop using itemprop attributes inside an itemtype=.../Product scope."""

    def parse(self, page):
        tree = LexborHTMLParser(page.html)
        product = tree.css_first('[itemtype$="schema.org/Product"]')
        if product is None:
            return []

        def prop(name):
            node = product.css_first(f'[itemprop="{name}"]')
            if node is None:
                return ""
            return (node.attributes.get("content") or node.attributes.get("href") or node.text(strip=True) or "").strip()

        price = parse_price(prop("price"))
        if price is None or price <= 0:
            return []
        return [OfferData(
            price=price,
            currency=prop("priceCurrency") or "PLN",
            title=prop("name"),
            sku=prop("sku"),
            mpn=prop("mpn") or prop("sku"),
            ean=prop("gtin13") or prop("gtin"),
            condition=parse_condition(prop("itemCondition")),
            in_stock=parse_availability(prop("availability")),
        )]
