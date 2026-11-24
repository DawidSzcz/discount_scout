"""Is this offer really the observed model? (PLAN.md section 5)

Deterministic steps only; the Gemini judge for unclear cases lives in llm.py and is used during
discovery, not on every price check.

1. exact model code in title/sku/mpn (normalised: case, spaces and dashes ignored) -> YES
2. EAN on both sides: equal -> YES, different -> NO
3. a sibling variant code in the title (UX8407AA-SN129X when observing -SN515X) -> NO
4. otherwise UNSURE
"""

import re
from dataclasses import dataclass

YES, NO, UNSURE = "yes", "no", "unsure"


@dataclass
class Match:
    verdict: str
    reason: str


def norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def _shape(s: str) -> str:
    """'SN515X' -> 'AADDDA': letters vs digits, to recognise sibling suffixes."""
    return "".join("D" if c.isdigit() else "A" for c in s)


def sibling_variant(code: str, text: str) -> str | None:
    """Return a different variant of the same base model mentioned in text, e.g. observing
    UX8407AA-SN515X and the title says UX8407AA-SN129X. Needs a base-suffix code (with a dash)."""
    if "-" not in code:
        return None
    base, suffix = code.rsplit("-", 1)
    base_n, suffix_n = norm(base), norm(suffix)
    if len(base_n) < 4 or not suffix_n:
        return None
    hay = norm(text)
    for m in re.finditer(re.escape(base_n), hay):
        follow = hay[m.end(): m.end() + len(suffix_n)]
        if len(follow) == len(suffix_n) and follow != suffix_n and _shape(follow) == _shape(suffix_n):
            return f"{base}-{follow}"
    return None


def match(code: str, ean: str, title: str = "", sku: str = "", mpn: str = "", offer_ean: str = "") -> Match:
    code_n = norm(code)
    if code_n and code_n in norm(" ".join([title, sku, mpn])):
        return Match(YES, f"model code {code} found")
    if ean and offer_ean:
        if ean.strip() == offer_ean.strip():
            return Match(YES, f"EAN {ean} matches")
        return Match(NO, f"EAN {offer_ean} differs from {ean}")
    other = sibling_variant(code, " ".join([title, sku, mpn]))
    if other:
        return Match(NO, f"different variant {other}")
    return Match(UNSURE, "model code not found on the page")


def match_offer(model, offer_data) -> Match:
    """Convenience wrapper for a ProductModel and a parsed OfferData."""
    return match(model.code, model.ean, offer_data.title, offer_data.sku, offer_data.mpn, offer_data.ean)
