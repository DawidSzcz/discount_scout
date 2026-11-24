"""Minimal Gemini client (REST, JSON answers). Used only during discovery, never on price checks.

As of 2026-11-24 the free key works with gemini-3.5-flash-lite for plain text; Google Search
grounding has no free quota (429) and the bigger flash models time out, so we don't use either.
Callers must cope with LLMError and fall back to deterministic logic.
"""

import json
import logging
import urllib.error
import urllib.request

from django.conf import settings

log = logging.getLogger(__name__)
API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class LLMError(Exception):
    pass


def available() -> bool:
    return bool(settings.GEMINI_API_KEY)


def generate_json(prompt: str, timeout: int = 60):
    if not available():
        raise LLMError("GEMINI_API_KEY is not set")
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
    }
    req = urllib.request.Request(
        API.format(model=settings.GEMINI_MODEL),
        data=json.dumps(body).encode(),
        headers={"x-goog-api-key": settings.GEMINI_API_KEY, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        raise LLMError(f"Gemini HTTP {e.code}: {e.read()[:200]!r}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise LLMError(f"Gemini unreachable: {e}") from e
    try:
        text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        return json.loads(text)
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        raise LLMError(f"unexpected Gemini answer: {str(data)[:200]}") from e


def group_models(query: str, hits: list[dict]) -> list[dict]:
    """Ceneo search hits -> distinct variants of the product the user means."""
    lines = "\n".join(f"{h['pid']} | {h['name']} | {h['price']}" for h in hits)
    prompt = f"""You help a user track prices of a product in Polish online shops.
The user wants to observe: "{query}"

Search results from Ceneo.pl, one per line (id | name | lowest price in PLN):
{lines}

List the distinct variants (exact manufacturer model codes) of the product the user means.
- Exclude accessories, spare parts, batteries, cases, chargers, and other product lines or older
  generations, unless the user's query names them.
- Several results can be the same variant listed twice (one titled with the model code, one with a
  manufacturer part number); merge them into one variant with all their ids.
- Use the manufacturer's model code format, e.g. "UX8407AA-SN515X" (keep the dash).
- description: the key specs that tell variants apart (CPU, RAM, storage, OS, colour), short.
- Only use ids from the list.

Answer with JSON: {{"models": [{{"code": "...", "description": "...", "ceneo_ids": ["..."]}}]}}"""
    data = generate_json(prompt)
    known = {h["pid"] for h in hits}
    out = []
    for m in data.get("models", []) if isinstance(data, dict) else []:
        code = str(m.get("code", "")).strip().upper()
        ids = [str(i) for i in m.get("ceneo_ids", []) if str(i) in known]
        if code and ids:
            out.append({"code": code, "description": str(m.get("description", ""))[:200], "ceneo_ids": ids})
    if not out and hits:
        raise LLMError("Gemini returned no usable models")
    return out


def judge_same_model(code: str, description: str, title: str) -> tuple[bool | None, str]:
    """Is an offer titled `title` the exact variant `code`? None when Gemini cannot tell."""
    prompt = f"""Is this shop offer the exact product variant {code} ({description})?
Offer title: "{title}"
Variants of one model differ only in a suffix (e.g. -SN515X vs -SN129X) and in specs like CPU,
RAM, storage or OS. Say "same": true only if the title's specs fit {code} and do not fit a
different variant; false if they contradict it; null if the title does not say enough.
Answer with JSON: {{"same": true|false|null, "reason": "short reason"}}"""
    data = generate_json(prompt, timeout=30)
    same = data.get("same") if isinstance(data, dict) else None
    return (same if isinstance(same, bool) else None), str(data.get("reason", ""))[:200]
