from decimal import Decimal

import pytest
from django.urls import reverse

from scout.models import Offer, PriceObservation, Product, ProductModel, SupportingOffer
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


# --- discovery wizard ----------------------------------------------------------------------------

from scout.models import DiscoveryRun  # noqa: E402


def _models_run(product):
    return DiscoveryRun.objects.create(product=product, query=product.name, status="done", results={"models": [
        {"code": "UX8407AA-SN515X", "description": "Ultra X9", "ceneo_ids": ["199125559"], "min_price": "12498.00",
         "names": ["Laptop Asus Zenbook Duo UX8407AA-SN515X"]},
        {"code": "UX8406CAIS99T", "description": "Ultra 9", "ceneo_ids": ["192536248"], "min_price": "10999.00",
         "names": ["Laptop Asus ZenBook Duo UX8406CA (UX8406CAIS99T)"]},
    ]})


def test_create_with_discovery_starts_a_run(client):
    r = client.post(reverse("product_create"), {"name": "Zenbook Duo", "active": "on", "discover": "on"})
    run = DiscoveryRun.objects.get()
    assert r.url == reverse("discovery_detail", args=[run.pk])
    assert run.query == "Zenbook Duo" and run.stage == "models"
    page = client.get(r.url)
    assert "Step 1 of 2" in page.text and 'hx-trigger="every 2s"' in page.text  # polls while running


def test_edit_form_has_no_discover_checkbox(client, model):
    r = client.get(reverse("product_edit", args=[model.product.pk]))
    assert "Find models and offers automatically" not in r.text


def test_models_step_shows_choices_and_creates_models(client, model):
    run = _models_run(model.product)
    page = client.get(reverse("discovery_detail", args=[run.pk]))
    assert "Which models do you want to observe?" in page.text and "every 2s" not in page.text
    assert "already added" in page.text  # SN515X exists on the product
    r = client.post(reverse("discovery_models", args=[run.pk]), {"pick": ["0", "1"], "code_0": "UX8407AA-SN515X",
                                                                 "code_1": "ux8406ca-is99t"})
    assert r.status_code == 302
    codes = set(model.product.variants.values_list("code", flat=True))
    assert codes == {"UX8407AA-SN515X", "UX8406CA-IS99T"}  # edited code used, existing one not duplicated
    run.refresh_from_db()
    assert run.stage == "offers" and run.status == "pending"
    assert [m["code"] for m in run.results["selected"]] == ["UX8407AA-SN515X", "UX8406CA-IS99T"]


def test_models_step_requires_a_choice(client, model):
    run = _models_run(model.product)
    r = client.post(reverse("discovery_models", args=[run.pk]), {}, follow=True)
    assert "Pick at least one model" in r.text


def test_offers_step_preselects_verified_and_creates_offers(client, model):
    run = DiscoveryRun.objects.create(product=model.product, query="q", stage="offers", status="done", results={
        "offers": {"UX8407AA-SN515X": [
            {"shop": "ceneo", "url": "https://www.ceneo.pl/199125559", "price": "12498.00", "seller": "deluxury.pl",
             "title": "t", "verdict": "yes", "reason": "Ceneo listing", "offer_count": 10},
            {"shop": "ceneo", "url": "https://www.ceneo.pl/199125553", "price": "13125.49", "seller": "x",
             "title": "t", "verdict": "yes", "reason": "Ceneo listing", "offer_count": 2},
            {"shop": "techlord", "url": "https://techlord.pl/p-39087.html", "price": "12499.00", "seller": "",
             "title": "t", "verdict": "yes", "reason": "model code found"},
            {"shop": "avans", "url": "https://www.avans.pl/sn129x", "price": "11399.00", "seller": "",
             "title": "t", "verdict": "no", "reason": "different variant UX8407AA-SN129X"},
        ]}})
    page = client.get(reverse("discovery_detail", args=[run.pk]))
    assert 'value="UX8407AA-SN515X|0" checked' in page.text  # main Ceneo listing
    assert 'value="UX8407AA-SN515X|1" >' in page.text or 'value="UX8407AA-SN515X|1" ' in page.text
    assert 'value="UX8407AA-SN515X|1" checked' not in page.text  # smaller duplicate listing
    assert 'value="UX8407AA-SN515X|3" checked' not in page.text  # different model
    client.post(reverse("discovery_offers", args=[run.pk]), {"offer": ["UX8407AA-SN515X|0", "UX8407AA-SN515X|2"]})
    offers = {o.shop: o for o in Offer.objects.filter(model=model)}
    assert set(offers) == {"ceneo", "techlord"}
    assert offers["ceneo"].kind == "aggregator" and offers["techlord"].match_confirmed
    run.refresh_from_db()
    assert run.results["applied"]



def test_offers_step_does_not_duplicate_observed_shops(client, offer):
    # offer fixture: x-kom URL already observed for the model
    run = DiscoveryRun.objects.create(product=offer.model.product, query="q", stage="offers", status="done", results={
        "offers": {"UX8407AA-SN515X": [
            {"shop": "xkom", "url": XKOM_URL, "price": "13349.00", "seller": "", "title": "t", "verdict": "yes", "reason": "r"},
            {"shop": "xkom", "url": XKOM_URL + "?v=2", "price": "13349.00", "seller": "", "title": "t", "verdict": "yes",
             "reason": "r"},
        ]}})
    page = client.get(reverse("discovery_detail", args=[run.pk]))
    assert "already observed" in page.text
    assert 'value="UX8407AA-SN515X|0"' not in page.text  # no checkbox for the observed URL
    assert 'value="UX8407AA-SN515X|1" checked' not in page.text  # same shop, other URL: not preselected
    assert "you already observe another x-kom URL" in page.text


def test_detail_lists_unsupported_shops_from_ceneo(client, offer):
    ceneo = Offer.objects.create(model=offer.model, shop="ceneo", kind=Offer.Kind.AGGREGATOR,
                                 url="https://www.ceneo.pl/199125559")
    PriceObservation.objects.create(offer=ceneo, price=Decimal("12600.29"), seller="allegro.pl", tier_used=2)
    SupportingOffer.objects.create(source=ceneo, seller="allegro.pl", title="Zenbook", price=Decimal("12600.29"),
                                   url="https://www.ceneo.pl/Click/Offer/?e=1")
    SupportingOffer.objects.create(source=ceneo, seller="sferis.pl", title="Zenbook", price=Decimal("13349"))
    html = client.get(reverse("product_detail", args=[offer.model.product_id])).content.decode()
    assert "Other shops on Ceneo" in html
    assert "allegro.pl" in html and "sferis.pl" in html
    assert html.count(">lowest<") == 1  # allegro is the lowest price right now

    ceneo.active = False
    ceneo.save()
    html = client.get(reverse("product_detail", args=[offer.model.product_id])).content.decode()
    assert "Other shops on Ceneo" not in html  # paused listing: its sellers are hidden


def test_unavailable_offer_is_flagged_and_not_best(client, offer):
    gone = Offer.objects.create(model=offer.model, shop="empik", url="https://www.empik.com/x,p1,agd-p")
    PriceObservation.objects.create(offer=gone, price=Decimal("6559"), in_stock=False, tier_used=2)
    html = client.get(reverse("product_detail", args=[offer.model.product_id])).content.decode()
    assert "not available" in html
    best = html.split("Best now", 1)[1][:400]
    assert "13 349" in best and "6 559" not in best
