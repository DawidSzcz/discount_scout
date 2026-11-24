"""Shops that work with plain HTTP (tier 1) as of the 2026-11-23 probe. Tier 2 stays as a fallback."""

import re
from urllib.parse import urljoin

from .base import register
from .structured import JsonLdShop, MicrodataShop


class XKomPlatform(JsonLdShop):
    """x-kom and Neonet run the same platform (identical product ids and JSON-LD).
    Search results are rendered from embedded JSON; result cards have generated class names, so
    the result links are read from the JSON ("productLink") instead."""

    search_url = "https://www.{host}/szukaj?q={q}"

    def result_links(self, page):
        base = page.final_url or page.url
        return [urljoin(base, m) for m in re.findall(r'"productLink":"(/p/[^"]+)"', page.html)]


@register
class XKom(XKomPlatform):
    key = "xkom"
    name = "x-kom"
    domains = ("x-kom.pl",)


@register
class Neonet(XKomPlatform):
    key = "neonet"
    name = "Neonet"
    domains = ("neonet.pl",)


@register
class Morele(JsonLdShop):
    key = "morele"
    name = "Morele.net"
    domains = ("morele.net",)
    search_url = "https://www.morele.net/wyszukiwarka/?q={q}"
    search_result_css = "a.product-card__name-link"


@register
class Deluxury(JsonLdShop):
    """Shoper platform: the Product is split over many JSON-LD blocks joined by @id."""

    key = "deluxury"
    name = "Deluxury.pl"
    domains = ("deluxury.pl",)
    search_url = "https://deluxury.pl/pl/searchquery/{q}"
    search_result_css = "product-tile a.link_no-underline"


@register
class MediaMarkt(JsonLdShop):
    """Product is nested in a BuyAction; only Product.offers count (not bundled add-ons)."""

    key = "mediamarkt"
    name = "MediaMarkt"
    domains = ("mediamarkt.pl",)
    search_url = "https://mediamarkt.pl/pl/search.html?query={q}"
    search_result_css = 'article a[href*="/product/"]'


@register
class TechLord(MicrodataShop):
    """No JSON-LD; schema.org microdata. itemprop=sku holds the manufacturer code."""

    key = "techlord"
    name = "TechLord.pl"
    domains = ("techlord.pl",)
    search_url = "https://techlord.pl/szukaj.html?szukaj={q}"
    search_result_css = "div.ElementListingRamka h3 a"
