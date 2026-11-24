"""Shop plugin interface (PLAN.md section 6). One subclass per shop, registered with @register."""

from dataclasses import dataclass
from decimal import Decimal
from typing import ClassVar
from urllib.parse import quote, urljoin, urlsplit

from selectolax.lexbor import LexborHTMLParser

from ..fetch import classify
from ..fetch.page import Page


@dataclass
class OfferData:
    """One offer parsed from a page. Single-shop pages yield one; aggregators yield one per seller."""

    price: Decimal
    currency: str = "PLN"
    title: str = ""
    sku: str = ""  # shop's own id
    mpn: str = ""  # manufacturer model code, e.g. UX8407AA-SN515X
    ean: str = ""
    seller: str = ""
    seller_url: str = ""
    condition: str = "new"  # new | used | refurbished | unknown
    in_stock: bool | None = None


class Shop:
    key: ClassVar[str]
    name: ClassVar[str]
    domains: ClassVar[tuple[str, ...]]
    kind: ClassVar[str] = "single"  # "single" | "aggregator"
    tiers: ClassVar[tuple[int, ...]] = (1, 2)  # fetch ladder, cheapest first
    keep_browser_cookies: ClassVar[bool] = True  # tier 2: reuse cookies between checks
    url_needs_query: ClassVar[bool] = False  # product URLs work without ?query (discovery strips it)
    # Shop search, the discovery fallback for shops not found on Ceneo.
    # {q} = the model code, {host} = the first domain (for platforms shared by several shops).
    search_url: ClassVar[str] = ""
    search_result_css: ClassVar[str] = ""  # anchors of result products; "" = any link to this shop
    search_max_results: ClassVar[int] = 3

    def search_page_url(self, code: str) -> str:
        return self.search_url.format(host=self.domains[0], q=quote(code))

    def result_links(self, page: Page) -> list[str]:
        """Product links on a search result page, in page order."""
        base = page.final_url or page.url
        css = self.search_result_css or "a[href]"
        return [urljoin(base, a.attributes.get("href") or "") for a in LexborHTMLParser(page.html or "<p></p>").css(css)]

    def search_links(self, page: Page, code: str) -> list[str]:
        """Candidate product URLs for `code` from a fetched search page. Links that contain the code
        come first. Some shops redirect an exact-code search straight to the product page."""
        key = _squash(code)
        final = (page.final_url or "").split("#")[0]
        searched = urlsplit(page.url).path
        if final and self.handles(final) and urlsplit(final).path != searched and key in _squash(urlsplit(final).path):
            return [final]
        links, seen = [], set()
        for href in self.result_links(page):
            href = href.split("#")[0]
            if href in seen or not self.handles(href) or urlsplit(href).path in ("", "/", searched):
                continue
            seen.add(href)
            links.append(href)
        if not self.search_result_css and type(self).result_links is Shop.result_links:
            links = [h for h in links if key in _squash(h)]  # any-link mode: only links naming the code
        links.sort(key=lambda h: key not in _squash(h))  # stable: page order otherwise
        if not links and final and self.handles(final) and urlsplit(final).path != searched:
            links = [final]
        return links[: self.search_max_results]

    def classify(self, page: Page) -> str:
        """Outcome of a fetched page; override for shop-specific challenges."""
        return classify(page)

    def parse(self, page: Page) -> list[OfferData]:
        raise NotImplementedError

    @classmethod
    def handles(cls, url: str) -> bool:
        host = (urlsplit(url).hostname or "").lower()
        return any(host == d or host.endswith("." + d) for d in cls.domains)


def _squash(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum())


_REGISTRY: dict[str, Shop] = {}


def register(cls: type[Shop]) -> type[Shop]:
    if cls.key in _REGISTRY:
        raise ValueError(f"duplicate shop key {cls.key}")
    _REGISTRY[cls.key] = cls()
    return cls


def get_shop(key: str) -> Shop:
    return _REGISTRY[key]


def shop_for_url(url: str) -> Shop | None:
    return next((s for s in _REGISTRY.values() if s.handles(url)), None)


def all_shops() -> list[Shop]:
    return list(_REGISTRY.values())
