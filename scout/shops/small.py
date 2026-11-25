"""Smaller shops found on Ceneo listings (2026-11-25 probe with Smeg FAB32LRD6). All serve the
price in plain HTTP (tier 1); tier 2 stays as a fallback. They have no shop search configured, so
discovery reaches them only through Ceneo."""

import json

from selectolax.lexbor import LexborHTMLParser

from .base import OfferData, Shop, register
from .structured import JsonLdShop, MicrodataShop, parse_price
from .tier2 import condition_from_title


@register
class AgdSmart(JsonLdShop):
    """Offers are often bundles ("+ Czajnik ..."); the price is the bundle's, as on Ceneo."""

    key = "agdsmart"
    name = "AGDsmart.pl"
    domains = ("agdsmart.pl",)


@register
class ElektroHome(JsonLdShop):
    """JSON-LD has the EAN but no model code; matching relies on the title and EAN."""

    key = "elektrohome"
    name = "ElektroHome.pl"
    domains = ("elektrohome.pl",)


@register
class KuchniaSklep(JsonLdShop):
    """The rendered page (tier 2) adds a second Product with the regular price (e.g. 9 499 zł next
    to 7 599 zł); the cheapest offer is the real one."""

    key = "kuchniasklep"
    name = "KuchniaSklep.pl"
    domains = ("kuchniasklep.pl",)


@register
class ELazienki(JsonLdShop):
    """mpn carries a brand prefix (smgFAB32LRD6)."""

    key = "elazienki"
    name = "eLazienki.pl"
    domains = ("elazienki.pl",)


@register
class AgdStyle(MicrodataShop):
    key = "agdstyle"
    name = "AGDstyle.pl"
    domains = ("agdstyle.pl",)


@register
class ElectroPoland(JsonLdShop):
    """IdoSell platform: mpn is written as "mpn:FAB32LRD6"."""

    key = "electropoland"
    name = "ElectroPoland.pl"
    domains = ("electropoland.pl",)


@register
class Smeg(JsonLdShop):
    """Smeg's official Polish store (www.smeg.com/pl/...)."""

    key = "smeg"
    name = "Smeg (oficjalny sklep)"
    domains = ("smeg.com",)


@register
class PiekneKuchnie(Shop):
    """WooCommerce without JSON-LD. The add-to-cart form of the main product carries a GTM data
    blob (sku, price, stock status); other products on the page have their own blobs outside that
    form, so only form.cart is read."""

    key = "pieknekuchnie"
    name = "PiekneKuchnie.com"
    domains = ("pieknekuchnie.com",)
    STOCK = {"instock": True, "outofstock": False}  # onbackorder: orderable, not in stock -> None

    def parse(self, page):
        node = LexborHTMLParser(page.html).css_first('form.cart input[name="gtm4wp_product_data"]')
        if node is None:
            return []
        try:
            data = json.loads(node.attributes.get("value") or "")
        except json.JSONDecodeError:
            return []
        price = parse_price(str(data.get("price", "")))
        if price is None or price <= 0:
            return []
        title = str(data.get("item_name", ""))
        return [OfferData(
            price=price,
            currency="PLN",
            title=title,
            sku=str(data.get("sku", "")),
            mpn=str(data.get("sku", "")),
            condition=condition_from_title(title),
            in_stock=self.STOCK.get(data.get("stockstatus")),
        )]
