from django.core.management.base import BaseCommand

from scout.checks import check_offer, due_offers
from scout.models import Offer


class Command(BaseCommand):
    help = "Run price checks right now, in this process (bypasses the job queue)."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--offer", type=int, action="append", help="offer id (repeatable)")
        group.add_argument("--due", action="store_true", help="all offers whose check is due")
        group.add_argument("--all", action="store_true", help="every active offer")

    def handle(self, offer, due, all, **opts):
        if offer:
            qs = Offer.objects.filter(pk__in=offer)
        elif due:
            qs = due_offers()
        else:
            qs = Offer.objects.filter(active=True)
        for o in qs.select_related("model__product__user"):
            obs = check_offer(o)
            o.refresh_from_db()
            result = f"{obs.price} {obs.currency} (tier {obs.tier_used})" if obs else "no price"
            flag = " SUSPICIOUS" if obs and obs.suspicious else ""
            self.stdout.write(f"#{o.pk} {o}: {result}{flag} -> status={o.status}")
