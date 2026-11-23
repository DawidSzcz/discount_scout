"""Shops that need a headless browser (tier 2) as of the 2026-11-23 probe: plain HTTP gets an
anti-bot page (Ceneo, Euro, Media Expert, Avans) or a page without the price (Empik)."""

import html
import re
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser

from ..fetch import Outcome
from .base import OfferData, Shop, register
from .structured import JsonLdShop, parse_price

# Offer titles that mean "not new". Ceneo and marketplaces mix these into the offer list.
NOT_NEW = re.compile(
    r"\b(outlet|powystawow\w*|ekspozycyjn\w*|u[zż]ywan\w*|odnowion\w*|refurbished|refurb|"
    r"po zwrocie|zwrot\w*|uszkodzon\w*|b-?grade|klasa b|demo)\b",
    re.I,
)


def condition_from_title(title: str) -> str:
    m = NOT_NEW.search(title or "")
    if not m:
        return "new"
    word = m.group(1).lower()
    return "refurbished" if word.startswith(("odnow", "refurb")) else "used"


@register
class Ceneo(Shop):
    """Price comparison site. One Ceneo product page = one model with offers from many shops;
    each check keeps the cheapest new offer (with the shop as seller)."""

    key = "ceneo"
    name = "Ceneo"
    domains = ("ceneo.pl",)
    kind = "aggregator"
    tiers = (2,)  # tier 1 gets a JS challenge page with status 200

    def classify(self, page):
        outcome = super().classify(page)
        # The challenge page is served with 200 and the homepage title; a real product page is
        # titled with the product name.
        if outcome == Outcome.OK and page.title.lower().startswith("ceneo - porównanie cen"):
            return Outcome.BLOCKED
        return outcome

    def parse(self, page):
        tree = LexborHTMLParser(page.html)
        offers = []
        for item in tree.css("li.product-offers__list__item"):
            attrs = item.attributes
            price = parse_price(attrs.get("data-price"))
            if price is None or price <= 0:
                continue
            name_node = item.css_first(".product-offer__product__offer-details__name")
            title = name_node.text(strip=True) if name_node else attrs.get("data-productname", "")
            title = html.unescape(title)  # some shops send double-encoded titles (&quot;)
            link = item.css_first('a[href^="/Click/Offer"]')
            offers.append(OfferData(
                price=price,
                currency="PLN",
                title=title,
                sku=attrs.get("data-productid") or "",
                seller=attrs.get("data-shopurl") or "",
                seller_url=urljoin("https://www.ceneo.pl/", link.attributes["href"]) if link else "",
                condition=condition_from_title(title),
                in_stock=True,  # Ceneo lists offers that can be bought
            ))
        return offers


@register
class Euro(JsonLdShop):
    """RTV EURO AGD (Akamai). OleOle runs on the same platform (v2)."""

    key = "euro"
    name = "RTV EURO AGD"
    domains = ("euro.com.pl",)
    tiers = (2,)


class MediaExpertPlatform(JsonLdShop):
    """Media Expert, Avans and Electro (v2) share one platform. Note: pages also show an
    "in instalments you only pay X" promo price; JSON-LD carries the real cash price."""

    tiers = (2,)


@register
class MediaExpert(MediaExpertPlatform):
    key = "mediaexpert"
    name = "Media Expert"
    domains = ("mediaexpert.pl",)


@register
class Avans(MediaExpertPlatform):
    key = "avans"
    name = "Avans"
    domains = ("avans.pl",)


@register
class Empik(Shop):
    """Marketplace without JSON-LD. The buy box shows the featured offer: price in
    data-ta="price" (or meta product:sale_price:amount), seller in data-ta="merchant-name".
    Tier 1 HTML has no price at all, so it is tier 2 only.
    The featured seller can change between checks and is not always the cheapest one on Empik;
    we track the featured offer (what the buy button sells)."""

    key = "empik"
    name = "Empik"
    domains = ("empik.com",)
    tiers = (2,)

    def parse(self, page):
        tree = LexborHTMLParser(page.html)

        def ta(name):
            node = tree.css_first(f'[data-ta="{name}"]')
            return node.text(strip=True) if node else ""

        def meta(prop):
            node = tree.css_first(f'meta[property="{prop}"]')
            return (node.attributes.get("content") or "").strip() if node else ""

        price = (
            parse_price(ta("price"))
            or parse_price(meta("product:sale_price:amount"))
            or parse_price(meta("product:price:amount"))
        )
        if price is None or price <= 0:
            return []
        title = ta("title") or meta("og:title")
        available = meta("product:availability")
        return [OfferData(
            price=price,
            currency="PLN",
            title=title,
            sku=meta("product:retailer_part_no"),
            seller=ta("merchant-name"),
            condition=condition_from_title(title),
            in_stock=True if available == "true" else False if available == "false" else None,
        )]
