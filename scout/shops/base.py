"""Shop plugin interface (PLAN.md section 6). One subclass per shop, registered with @register."""

from dataclasses import dataclass
from decimal import Decimal
from typing import ClassVar
from urllib.parse import urlsplit

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

    def classify(self, page: Page) -> str:
        """Outcome of a fetched page; override for shop-specific challenges."""
        return classify(page)

    def parse(self, page: Page) -> list[OfferData]:
        raise NotImplementedError

    @classmethod
    def handles(cls, url: str) -> bool:
        host = (urlsplit(url).hostname or "").lower()
        return any(host == d or host.endswith("." + d) for d in cls.domains)


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
