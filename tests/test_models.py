from decimal import Decimal

import pytest

from scout.models import Offer, PriceObservation, Product, ProductModel, Settings
from scout.owner import get_owner


@pytest.mark.django_db
def test_owner_gets_default_settings():
    owner = get_owner()
    assert get_owner() == owner  # idempotent
    s = Settings.objects.get(user=owner)
    assert (s.check_interval_hours, s.outlier_pct, s.broken_after_failures) == (4, 40, 3)


@pytest.mark.django_db
def test_product_tree():
    owner = get_owner()
    product = Product.objects.create(user=owner, name="Zenbook Duo")
    model = ProductModel.objects.create(product=product, code="UX8407AA-SN515X", ean="4711636433600")
    offer = Offer.objects.create(model=model, shop="xkom", url="https://www.x-kom.pl/p/1610557")
    PriceObservation.objects.create(offer=offer, price=Decimal("13349.00"), tier_used=1)
    assert offer.status == Offer.Status.OK
    assert product.variants.get().offers.get().observations.get().price == Decimal("13349.00")
