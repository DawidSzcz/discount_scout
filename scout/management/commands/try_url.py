from django.core.management.base import BaseCommand, CommandError

from scout.fetch import Outcome, fetch
from scout.shops import shop_for_url


class Command(BaseCommand):
    help = "Fetch a shop URL along its tier ladder and print what the parser extracts (no DB writes)."

    def add_arguments(self, parser):
        parser.add_argument("url")
        parser.add_argument("--tier", type=int, help="force one tier instead of the shop's ladder")

    def handle(self, url, tier, **opts):
        shop = shop_for_url(url)
        if shop is None:
            raise CommandError("shop not supported yet")
        for t in [tier] if tier else shop.tiers:
            page = fetch(url, shop.key, t)
            outcome = shop.classify(page)
            self.stdout.write(f"[{shop.key}] tier {t}: status={page.status} outcome={outcome}")
            if outcome != Outcome.OK:
                continue
            offers = shop.parse(page)
            if not offers:
                self.stdout.write("  no offers parsed")
                continue
            for o in offers:
                self.stdout.write(
                    f"  {o.price} {o.currency} | {o.condition} | in_stock={o.in_stock} | mpn={o.mpn or '-'} "
                    f"| ean={o.ean or '-'} | seller={o.seller or '-'} | {o.title[:70]}"
                )
            return
        self.stderr.write("all tiers failed")
