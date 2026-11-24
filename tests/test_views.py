from decimal import Decimal

import pytest
from django.urls import reverse

from scout.models import Offer, PriceObservation, Product, ProductModel
from scout.owner import get_owner

pytestmark = pytest.mark.django_db

XKOM_URL = "https://www.x-kom.pl/p/1610557-laptop-14-asus-zenbook-duo.html"


@pytest.fixture
def model():
    product = Product.objects.create(user=get_owner(), name="Zenbook Duo")
    return ProductModel.objects.create(product=product, code="UX8407AA-SN515X")


@pytest.fixture
def offer(model):
    o = Offer.objects.create(model=model, shop="xkom", url=XKOM_URL)
    PriceObservation.objects.create(offer=o, price=Decimal("13349"), tier_used=1)
    return o


def test_empty_product_list(client):
    r = client.get(reverse("product_list"))
    assert r.status_code == 200
    assert b"Nothing observed yet" in r.content


def test_product_list_shows_best_price(client, offer):
    r = client.get(reverse("product_list"))
    assert "Zenbook Duo" in r.text
    assert "13 349,00 zł" in r.text
    assert "x-kom" in r.text


def test_create_product_and_reject_duplicate(client):
    r = client.post(reverse("product_create"), {"name": "Zenbook Duo", "active": "on"})
    product = Product.objects.get()
    assert r.status_code == 302 and r.url == reverse("product_detail", args=[product.pk])
    assert product.user == get_owner()
    r = client.post(reverse("product_create"), {"name": "zenbook duo", "active": "on"})
    assert r.status_code == 200 and "already observe" in r.text


def test_detail_page_with_chart(client, offer):
    r = client.get(reverse("product_detail", args=[offer.model.product.pk]))
    assert r.status_code == 200
    assert "UX8407AA-SN515X" in r.text
    assert f'id="chart-{offer.model.pk}"' in r.text  # chart data embedded
    assert '"y": 13349.0' in r.text
    assert '"label": "x-kom"' in r.text  # shop name, not key


def test_chart_extends_active_offer_to_now(offer):
    from scout.queries import chart_data

    from datetime import timedelta

    from django.utils import timezone

    offer.observations.update(fetched_at=timezone.now() - timedelta(hours=1))
    (dataset,) = chart_data(offer.model)["datasets"]
    assert len(dataset["data"]) == 2 and dataset["data"][0]["y"] == dataset["data"][1]["y"] == 13349.0
    offer.active = False
    offer.save()
    assert len(chart_data(offer.model)["datasets"][0]["data"]) == 1


def test_add_model_normalises_code(client, model):
    client.post(reverse("model_create", args=[model.product.pk]), {"code": " ux8407aa-sn129x ", "ean": ""})
    assert model.product.variants.filter(code="UX8407AA-SN129X").exists()


def test_add_offer_supported_shop(client, model):
    r = client.post(reverse("offer_create", args=[model.pk]), {"url": XKOM_URL})
    assert r.status_code == 302
    offer = Offer.objects.get()
    assert (offer.shop, offer.kind, offer.model) == ("xkom", "single", model)


def test_add_offer_unsupported_shop_is_rejected(client, model):
    r = client.post(reverse("offer_create", args=[model.pk]), {"url": "https://allegro.pl/produkt/x"}, follow=True)
    assert not Offer.objects.exists()
    assert "Shop not supported yet" in r.text


def test_offer_toggle_returns_row(client, offer):
    r = client.post(reverse("offer_toggle", args=[offer.pk]), HTTP_HX_REQUEST="true")
    offer.refresh_from_db()
    assert not offer.active
    assert f'id="offer-{offer.pk}"' in r.text and "Resume" in r.text


def test_offer_check_queues_job_once(client, offer):
    r1 = client.post(reverse("offer_check", args=[offer.pk]), HTTP_HX_REQUEST="true")
    r2 = client.post(reverse("offer_check", args=[offer.pk]), HTTP_HX_REQUEST="true")
    assert "Check queued" in r1.text
    assert "already queued" in r2.text


def test_offer_delete(client, offer):
    r = client.post(reverse("offer_delete", args=[offer.pk]), HTTP_HX_REQUEST="true")
    assert r.status_code == 200 and r.text.strip() == ""
    assert not Offer.objects.exists()


def test_offer_history_page(client, offer):
    r = client.get(reverse("offer_detail", args=[offer.pk]))
    assert r.status_code == 200 and "13 349,00 zł" in r.text


def test_settings_save_and_validate(client):
    data = {"check_interval_hours": 6, "summary_interval_hours": 12, "notify_email": "",
            "outlier_pct": 40, "broken_after_failures": 3}
    assert client.post(reverse("settings"), data).status_code == 302
    assert get_owner().scout_settings.check_interval_hours == 6
    r = client.post(reverse("settings"), data | {"check_interval_hours": 0})
    assert r.status_code == 200 and "At least 1 hour" in r.text


def test_delete_product_cascades(client, offer):
    client.post(reverse("product_delete", args=[offer.model.product.pk]))
    assert not Product.objects.exists() and not PriceObservation.objects.exists()


def test_review_same_model_confirms_and_resumes(client, offer):
    from scout.models import MatchReview

    offer.status = Offer.Status.NEEDS_REVIEW
    offer.save()
    review = MatchReview.objects.create(offer=offer, candidate_title="ASUS Zenbook Duo", candidate_url=offer.url,
                                        reason="different variant UX8407AA-SN129X")
    page = client.get(reverse("product_detail", args=[offer.model.product.pk]))
    assert "Is this the same model?" in page.text
    client.post(reverse("review_decide", args=[review.pk]), {"decision": "same"})
    offer.refresh_from_db()
    review.refresh_from_db()
    assert review.decision is True and offer.match_confirmed and offer.status == Offer.Status.OK


def test_review_different_model_pauses_offer(client, offer):
    from scout.models import MatchReview

    review = MatchReview.objects.create(offer=offer, candidate_title="x", candidate_url=offer.url, reason="r")
    client.post(reverse("review_decide", args=[review.pk]), {"decision": "different"})
    offer.refresh_from_db()
    assert not offer.active
