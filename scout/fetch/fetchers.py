"""Fetch tiers (PLAN.md section 6).

Tier 1: curl_cffi impersonating Chrome's TLS/HTTP2 fingerprint. Fast, no JS.
Tier 2: headless Chromium via Playwright + stealth patches. Runs JS; cookies are kept per shop
        in var/browser_state/<shop>.json so anti-bot cookies survive between checks.
Tier 3 (real Chrome profile) is postponed to v2.
"""

import json
import logging
from pathlib import Path

from django.conf import settings

from .page import Page

log = logging.getLogger(__name__)

HEADERS = {"Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7"}
TIMEOUT_S = 30

_sessions = {}  # shop key -> curl_cffi Session (keeps cookies for the life of the process)


def fetch_tier1(url: str, shop_key: str) -> Page:
    from curl_cffi import requests
    from curl_cffi.requests.exceptions import RequestException, Timeout

    session = _sessions.get(shop_key)
    if session is None:
        session = _sessions[shop_key] = requests.Session(impersonate="chrome", headers=HEADERS)
    try:
        resp = session.get(url, timeout=TIMEOUT_S, allow_redirects=True)
    except Timeout as e:
        return Page(url=url, tier=1, error=f"timeout: {e}")
    except RequestException as e:
        return Page(url=url, tier=1, error=f"{type(e).__name__}: {e}"[:500])
    return Page(url=url, tier=1, status=resp.status_code, html=resp.text, final_url=str(resp.url))


def _state_file(shop_key: str) -> Path:
    d = Path(settings.SCOUT_VAR_DIR) / "browser_state"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{shop_key}.json"


def fetch_tier2(url: str, shop_key: str, settle_ms: int = 6000) -> Page:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth

    state = _state_file(shop_key)
    with Stealth().use_sync(sync_playwright()) as p:
        browser = p.chromium.launch(headless=True)
        try:
            ctx = browser.new_context(
                locale="pl-PL",
                timezone_id="Europe/Warsaw",
                viewport={"width": 1366, "height": 850},
                extra_http_headers=HEADERS,
                storage_state=str(state) if state.exists() else None,
            )
            page = ctx.new_page()
            try:
                resp = page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_S * 1000)
                page.wait_for_timeout(settle_ms)  # let JS challenges and price widgets finish
                html = page.content()
                status = resp.status if resp else None
                final_url = page.url
            except PlaywrightTimeout as e:
                return Page(url=url, tier=2, error=f"timeout: {e}"[:500])
            except PlaywrightError as e:
                return Page(url=url, tier=2, error=f"{type(e).__name__}: {e}"[:500])
            try:
                state.write_text(json.dumps(ctx.storage_state()))
            except Exception:  # cookie persistence is best-effort
                log.warning("could not save browser state for %s", shop_key, exc_info=True)
            return Page(url=url, tier=2, status=status, html=html, final_url=final_url)
        finally:
            browser.close()


FETCHERS = {1: fetch_tier1, 2: fetch_tier2}


def fetch(url: str, shop_key: str, tier: int) -> Page:
    try:
        fetcher = FETCHERS[tier]
    except KeyError:
        raise ValueError(f"unsupported fetch tier {tier}") from None
    return fetcher(url, shop_key)
