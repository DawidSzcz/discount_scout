"""Background jobs, run by the worker container (`manage.py procrastinate worker`).

The worker runs one job at a time, so checks are sequential and per-shop spacing stays simple.
Checks missed while the PC was off are simply overdue and run once on the next dispatch.
"""

import logging

from procrastinate.contrib.django import app
from procrastinate.exceptions import AlreadyEnqueued

from .checks import check_offer, due_offers
from .models import Offer

log = logging.getLogger(__name__)


@app.periodic(cron="*/5 * * * *")
@app.task(queueing_lock="dispatch_checks", pass_context=False)
def dispatch_checks(timestamp: int):
    queued = 0
    for offer_id in due_offers().values_list("id", flat=True):
        try:
            check_offer_task.configure(queueing_lock=f"check_offer-{offer_id}").defer(offer_id=offer_id)
            queued += 1
        except AlreadyEnqueued:
            pass
    if queued:
        log.info("queued %d offer checks", queued)


@app.task(pass_context=False)
def check_offer_task(offer_id: int):
    try:
        offer = Offer.objects.select_related("model__product__user").get(pk=offer_id)
    except Offer.DoesNotExist:
        return  # deleted while queued
    check_offer(offer)
