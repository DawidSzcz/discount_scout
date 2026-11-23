"""Per-shop request spacing: requests to the same shop never run in parallel and are spaced by a
random gap (settings.SCOUT_SHOP_GAP_SECONDS). Uses a row lock on ShopState so it also holds across
several worker processes."""

import random
import time

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from ..models import ShopState


def wait_for_slot(shop_key: str, sleep=time.sleep) -> float:
    """Block until this shop may be hit again, then claim the slot. Returns seconds waited."""
    lo, hi = settings.SCOUT_SHOP_GAP_SECONDS
    with transaction.atomic():
        state, _ = ShopState.objects.select_for_update().get_or_create(key=shop_key)
        waited = 0.0
        if state.last_request_at:
            ready_at = state.last_request_at.timestamp() + random.uniform(lo, hi)
            waited = max(0.0, ready_at - timezone.now().timestamp())
            if waited:
                sleep(waited)
        state.last_request_at = timezone.now()
        state.save(update_fields=["last_request_at"])
    return waited
