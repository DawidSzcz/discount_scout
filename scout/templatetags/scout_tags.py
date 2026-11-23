from django import template

from scout.notify import fmt_price, offer_link as _offer_link
from scout.shops import get_shop

register = template.Library()

STATUS_CLASS = {"ok": "ok", "suspicious": "warn", "needs_review": "warn", "blocked": "bad", "broken": "bad", "gone": "bad"}


@register.filter
def pln(value):
    return fmt_price(value) if value is not None else ""


@register.filter
def shop_name(key):
    try:
        return get_shop(key).name
    except KeyError:
        return key


@register.filter
def offer_link(observation):
    return _offer_link(observation)


@register.filter
def status_class(status):
    return STATUS_CLASS.get(status, "")
