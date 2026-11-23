"""Shops that work with plain HTTP (tier 1) as of the 2026-11-23 probe. Tier 2 stays as a fallback."""

from .base import register
from .structured import JsonLdShop, MicrodataShop


class XKomPlatform(JsonLdShop):
    """x-kom and Neonet run the same platform (identical product ids and JSON-LD)."""


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


@register
class Deluxury(JsonLdShop):
    """Shoper platform: the Product is split over many JSON-LD blocks joined by @id."""

    key = "deluxury"
    name = "Deluxury.pl"
    domains = ("deluxury.pl",)


@register
class MediaMarkt(JsonLdShop):
    """Product is nested in a BuyAction; only Product.offers count (not bundled add-ons)."""

    key = "mediamarkt"
    name = "MediaMarkt"
    domains = ("mediamarkt.pl",)


@register
class TechLord(MicrodataShop):
    """No JSON-LD; schema.org microdata. itemprop=sku holds the manufacturer code."""

    key = "techlord"
    name = "TechLord.pl"
    domains = ("techlord.pl",)
