"""Saved-page fixtures for parser tests: tests/fixtures/<shop>/<name>.<status>.html.gz

Pages are gzipped (shop pages are ~1 MB each) and IPv4 addresses are scrubbed, because block
pages echo the visitor's IP back.
"""

import gzip
import re
from pathlib import Path

from django.conf import settings

from .fetch.page import Page

FIXTURES_DIR = Path(settings.BASE_DIR) / "tests" / "fixtures"
_IPV4 = re.compile(r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\d.])")
PLACEHOLDER_IP = "203.0.113.1"  # RFC 5737 documentation address


def scrub(html: str) -> str:
    return _IPV4.sub(PLACEHOLDER_IP, html)


def save_fixture(page: Page, shop_key: str, name: str) -> Path:
    path = FIXTURES_DIR / shop_key / f"{name}.{page.status or 0}.html.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(scrub(page.html).encode(), mtime=0))
    return path


def load_fixture(shop_key: str, name: str, tier: int = 1) -> Page:
    matches = sorted((FIXTURES_DIR / shop_key).glob(f"{name}.*.html.gz"))
    if len(matches) != 1:
        raise FileNotFoundError(f"expected one fixture {shop_key}/{name}.*.html.gz, found {matches}")
    path = matches[0]
    status = int(path.name.split(".")[-3])
    html = gzip.decompress(path.read_bytes()).decode()
    return Page(url=f"https://fixture/{shop_key}/{name}", tier=tier, status=status, html=html)
