"""Fetched page + generic classification of anti-bot blocks and HTTP errors."""

import html
import re
from dataclasses import dataclass, field
from datetime import datetime

from django.utils import timezone


@dataclass
class Page:
    url: str
    tier: int
    status: int | None = None  # None when the request itself failed
    html: str = ""
    final_url: str = ""
    error: str = ""  # "timeout" / exception text when status is None
    fetched_at: datetime = field(default_factory=timezone.now)

    @property
    def title(self) -> str:
        m = re.search(r"<title[^>]*>(.*?)</title>", self.html, re.I | re.S)
        return html.unescape(re.sub(r"\s+", " ", m.group(1))).strip() if m else ""


class Outcome:
    OK = "ok"
    NOT_FOUND = "not_found"
    BLOCKED = "blocked"
    CAPTCHA = "captcha"
    HTTP_ERROR = "http_error"
    TIMEOUT = "timeout"


# Titles of interstitial pages seen on Polish shops (see PLAN.md section 9).
BLOCK_TITLE_MARKERS = (
    "just a moment",  # Cloudflare challenge
    "attention required",  # Cloudflare block
    "blokada",  # Euro / OleOle (Akamai)
    "cierpliwości",  # Electro / Komputronik challenge ("patience...")
    "access denied",
    "are you a robot",
    "jesteś robotem",
)
CAPTCHA_MARKERS = ("cf-turnstile", "g-recaptcha", "h-captcha", "captcha-delivery.com")
BLOCK_STATUSES = {401, 403, 429, 503}


def classify(page: Page) -> str:
    """Generic outcome for a fetched page. Shops can refine it (e.g. Ceneo's 200-status JS challenge)."""
    if page.status is None:
        return Outcome.TIMEOUT if "timeout" in page.error.lower() else Outcome.HTTP_ERROR
    if page.status in (404, 410):
        return Outcome.NOT_FOUND
    title = page.title.lower()
    blocked_title = any(m in title for m in BLOCK_TITLE_MARKERS)
    if page.status in BLOCK_STATUSES or blocked_title:
        # A real captcha widget means a human could pass; plain blocks don't offer that.
        lowered = page.html.lower()
        if len(page.html) < 200_000 and any(m in lowered for m in CAPTCHA_MARKERS):
            return Outcome.CAPTCHA
        return Outcome.BLOCKED
    if page.status >= 400:
        return Outcome.HTTP_ERROR
    return Outcome.OK
