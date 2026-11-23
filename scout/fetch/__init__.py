from .fetchers import fetch
from .page import Outcome, Page, classify
from .politeness import wait_for_slot

__all__ = ["Outcome", "Page", "classify", "fetch", "polite_fetch", "wait_for_slot"]


def polite_fetch(url: str, shop_key: str, tier: int) -> Page:
    """Fetch respecting the per-shop spacing. Use this everywhere except one-off tools."""
    wait_for_slot(shop_key)
    return fetch(url, shop_key, tier)
