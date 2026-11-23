from django.core.management.base import BaseCommand

from scout.fetch import classify, fetch
from scout.fixtures import save_fixture


class Command(BaseCommand):
    help = "Fetch a URL with a given tier and save it as a parser test fixture."

    def add_arguments(self, parser):
        parser.add_argument("url")
        parser.add_argument("--shop", required=True, help="shop key, e.g. xkom (fixture folder name)")
        parser.add_argument("--name", default="product", help="fixture name (default: product)")
        parser.add_argument("--tier", type=int, default=1, choices=[1, 2])

    def handle(self, url, shop, name, tier, **opts):
        page = fetch(url, shop, tier)
        outcome = classify(page)
        self.stdout.write(f"tier {tier}: status={page.status} outcome={outcome} title={page.title[:80]!r}")
        if page.status is None:
            self.stderr.write(f"request failed: {page.error}")
            return
        path = save_fixture(page, shop, name)
        self.stdout.write(self.style.SUCCESS(f"saved {path}"))
