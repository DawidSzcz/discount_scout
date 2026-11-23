"""Background jobs, run by the worker container (`manage.py procrastinate worker`).

The worker runs one job at a time, so checks are sequential and per-shop spacing stays simple.
Checks missed while the PC was off are simply overdue and run once on the next dispatch.
"""

import logging

from procrastinate.contrib.django import app
from procrastinate.exceptions import AlreadyEnqueued

from .checks import check_offer, due_offers
from .models import Offer, Settings
from .notify import maybe_alert, send_summary, summary_due

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
    obs = check_offer(offer)
    if obs:
        maybe_alert(obs)


@app.periodic(cron="*/15 * * * *")
@app.task(queueing_lock="send_summaries", pass_context=False)
def send_summaries(timestamp: int):
    for cfg in Settings.objects.select_related("user"):
        if summary_due(cfg):
            send_summary(cfg)
