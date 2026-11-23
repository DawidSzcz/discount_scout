from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from scout.models import CheckFailure, MatchReview, Offer, PriceObservation, Product, ProductModel
from scout.notify import fmt_price, maybe_alert, send_summary, summary_due
from scout.owner import get_owner

pytestmark = pytest.mark.django_db


@pytest.fixture
def cfg():
    owner = get_owner()
    s = owner.scout_settings
    s.notify_email = "me@example.com"
    s.save()
    return s


@pytest.fixture
def model(cfg):
    product = Product.objects.create(user=cfg.user, name="Zenbook Duo")
    return ProductModel.objects.create(product=product, code="UX8407AA-SN515X")


def make_offer(model, shop="xkom", url=None):
    return Offer.objects.create(model=model, shop=shop, url=url or f"https://{shop}.example/p/1")


def observe(offer, price, minutes_ago=0, **kw):
    return PriceObservation.objects.create(
        offer=offer, price=Decimal(price), tier_used=1,
        fetched_at=timezone.now() - timedelta(minutes=minutes_ago), **kw,
    )


def test_fmt_price():
    assert fmt_price(Decimal("12499.5")) == "12 499,50 zł"
    assert fmt_price(Decimal("999")) == "999,00 zł"


# --- alerts --------------------------------------------------------------------------------------


def test_first_price_is_baseline_not_alert(model, mailoutbox):
    assert not maybe_alert(observe(make_offer(model), "13349"))
    assert mailoutbox == []


def test_new_all_time_low_across_shops_alerts(model, mailoutbox):
    xkom, techlord = make_offer(model, "xkom"), make_offer(model, "techlord")
    observe(xkom, "13349", minutes_ago=60)
    observe(techlord, "12999", minutes_ago=30)
    assert maybe_alert(observe(techlord, "12499"))
    (mail,) = mailoutbox
    assert mail.to == ["me@example.com"]
    assert mail.subject == "New low: UX8407AA-SN515X 12 499,00 zł at TechLord.pl"
    assert "previous low: 12 999,00 zł (-500,00 zł, -3.8%)" in mail.body
    assert "https://techlord.example/p/1" in mail.body


def test_no_alert_when_not_below_all_time_low(model, mailoutbox):
    offer = make_offer(model)
    observe(offer, "7999", minutes_ago=300)  # old deal
    observe(offer, "8499", minutes_ago=200)  # deal ended
    assert not maybe_alert(observe(offer, "8199"))  # falls back, but above all-time low
    assert not maybe_alert(observe(offer, "7999"))  # equal is not lower
    assert mailoutbox == []


def test_suspicious_prices_never_alert_nor_set_the_low(model, mailoutbox):
    offer = make_offer(model)
    observe(offer, "13349", minutes_ago=60)
    assert not maybe_alert(observe(offer, "333", minutes_ago=30, suspicious=True))
    assert maybe_alert(observe(offer, "13000"))  # compared with 13349, not 333


def test_alert_falls_back_to_env_recipient(model, cfg, settings, mailoutbox):
    cfg.notify_email = ""
    cfg.save()
    settings.SCOUT_NOTIFY_EMAIL = "env@example.com"
    offer = make_offer(model)
    observe(offer, "100", minutes_ago=5)
    maybe_alert(observe(offer, "90"))
    assert mailoutbox[0].to == ["env@example.com"]


def test_no_recipient_means_no_email(model, cfg, settings, mailoutbox):
    cfg.notify_email = ""
    cfg.save()
    settings.SCOUT_NOTIFY_EMAIL = ""
    offer = make_offer(model)
    observe(offer, "100", minutes_ago=5)
    assert not maybe_alert(observe(offer, "90"))
    assert mailoutbox == []


# --- summary -------------------------------------------------------------------------------------


def test_summary_lists_best_price_per_model(model, cfg, mailoutbox):
    xkom, techlord = make_offer(model, "xkom"), make_offer(model, "techlord")
    observe(xkom, "13349")
    observe(techlord, "12499")
    other = ProductModel.objects.create(product=model.product, code="UX8407AA-SN129X")
    assert send_summary(cfg)
    body = mailoutbox[0].body
    assert mailoutbox[0].subject == "discount_scout summary"
    assert "UX8407AA-SN515X: 12 499,00 zł at TechLord.pl" in body
    assert "https://techlord.example/p/1" in body
    assert f"{other.code}: no price yet" in body
    assert "PROBLEMS" not in body


def test_summary_uses_latest_price_not_historic(model, cfg, mailoutbox):
    offer = make_offer(model)
    observe(offer, "9999", minutes_ago=600)
    observe(offer, "13349")
    send_summary(cfg)
    assert "13 349,00 zł" in mailoutbox[0].body


def test_summary_skipped_when_nothing_changed(model, cfg, mailoutbox):
    offer = make_offer(model)
    observe(offer, "13349", minutes_ago=120)
    assert send_summary(cfg, now=timezone.now() - timedelta(minutes=60))
    observe(offer, "13349", minutes_ago=10)  # same price again
    assert not send_summary(cfg)
    observe(offer, "13299", minutes_ago=0)  # changed
    assert send_summary(cfg)
    assert len(mailoutbox) == 2


def test_summary_problems_section_and_failures_reported_once(model, cfg, mailoutbox):
    blocked = make_offer(model, "deluxury")
    blocked.status = Offer.Status.BROKEN
    blocked.save()
    for _ in range(3):
        CheckFailure.objects.create(offer=blocked, reason="blocked", tier=1, http_status=403)
    observe(make_offer(model, "xkom"), "333", suspicious=True)
    MatchReview.objects.create(offer=blocked, candidate_title="x", candidate_url="https://x.example")

    assert send_summary(cfg)
    body = mailoutbox[0].body
    assert mailoutbox[0].subject == "discount_scout summary + problems"
    assert "UX8407AA-SN515X @ Deluxury.pl: blocked x3" in body
    assert "UX8407AA-SN515X @ Deluxury.pl: broken" in body
    assert "Suspicious prices held back" in body and "333,00 zł" in body
    assert "Matches needing review: 1" in body
    assert not CheckFailure.objects.filter(reported=False).exists()


def test_summary_due(cfg):
    now = timezone.now()
    assert summary_due(cfg, now)  # never sent
    cfg.last_summary_at = now - timedelta(hours=23)
    assert not summary_due(cfg, now)
    cfg.last_summary_at = now - timedelta(hours=24)
    assert summary_due(cfg, now)
