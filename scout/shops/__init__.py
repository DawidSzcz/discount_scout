"""Supported shops. Importing this package registers every shop class.

To add a shop: subclass JsonLdShop / MicrodataShop / Shop in a module here, decorate with @register,
capture a fixture (manage.py capture URL --shop KEY) and add a test in tests/test_shops.py.
"""

from . import tier1, tier2  # noqa: F401  (registers shops)
from .base import OfferData, Shop, all_shops, get_shop, register, shop_for_url

__all__ = ["OfferData", "Shop", "all_shops", "get_shop", "register", "shop_for_url"]
