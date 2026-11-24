from decimal import Decimal, InvalidOperation

from django import template

from scout.notify import fmt_price, offer_link as _offer_link
from scout.shops import get_shop

register = template.Library()

STATUS_CLASS = {"ok": "ok", "suspicious": "warn", "needs_review": "warn", "blocked": "bad", "broken": "bad", "gone": "bad"}


@register.filter
def pln(value):
    if value is None or value == "":
        return ""
    try:
        return fmt_price(Decimal(str(value)))  # discovery results store prices as strings
    except InvalidOperation:
        return str(value)


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
