# discount_scout - Plan

Decisions come from the design interview (2026-11-23). The original requirements are in `SPEC.md`.

## 1. Scope

- **v1 is for one user** (the owner). It runs on the owner's Linux PC and is reachable only at `localhost`, with **no login**.
- **Designed to go public later.** Every user-owned table has a `user_id` FK (pointing at a single seeded user in v1), so adding auth later means no data migration.
- **v1 shops (11, all confirmed working in the probe):** x-kom, Neonet, Morele, Deluxury, TechLord, MediaMarkt (tier 1); Ceneo, Euro, Media Expert, Avans, Empik (tier 2).
- **Postponed to v2:** Allegro (via official API), OleOle, Electro, Komputronik, ASUS eStore (all blocked; need tier 3 or the API).
- **Out of scope for v1:** a seller/offer blocklist ("not trusted enough"), paid proxies or scraping APIs, non-PLN currencies, and other notification channels.

## 2. Stack

| Concern | Choice |
|---|---|
| Language | Python 3.12+, managed with `uv` |
| Web | Django + HTMX (server-rendered); Django admin for raw CRUD |
| DB | PostgreSQL |
| Background jobs | Postgres-backed queue (Procrastinate, or django-q2 with the ORM broker), periodic + on-demand tasks, retries |
| Fetch tier 1 | `curl_cffi` with browser TLS impersonation (`impersonate="chrome"`) |
| Fetch tier 2 | Playwright Chromium + `playwright-stealth` |
| Fetch tier 3 *(v2)* | Playwright with a persistent real Chrome profile (headed, cookies kept) |
| HTML parsing | `selectolax` (lexbor backend), plus JSON-LD extraction |
| LLM | Gemini with Google Search grounding, structured JSON output |
| Email | Gmail SMTP with an app password, via Django's email backend |
| Charts | Chart.js (price history) |
| Runtime | docker-compose: `web`, `worker`, `db` (worker uses the official Playwright image) |

The containers use the host's home connection, so the **residential IP** is kept. Checks missed while the PC was off are not piled up: on startup the scheduler runs any offers that are overdue, once each.

## 3. Domain model

```
User
 +- Product            "Zenbook Duo"           (name, created_at, active)
     +- Model          "UX8407AA-SN515X"       (code, ean?, specs_json, active)
         +- Offer      one observed URL        (shop, url, kind: single|aggregator,
             |                                  status: ok|broken|gone|blocked|suspicious|needs_review,
             |                                  consecutive_failures, next_check_at)
             +- PriceObservation               (fetched_at, price, currency, seller?, seller_url?,
                                                condition, tier_used, raw_snapshot_ref)
CheckFailure        (offer, at, reason: blocked|captcha|http_error|parse_error|no_match, tier, detail)
MatchReview         (offer, candidate_title, candidate_url, reason, resolved)
DiscoveryRun        (product, status, progress_log, results_json)  - drives the live wizard page
Settings            (singleton per user: check_interval_h, summary_interval_h, notify_email,
                     outlier_pct=40, broken_after_n=3)
```

- **Aggregator offers** (Allegro product page, Ceneo listing): each check saves **one** `PriceObservation`, the cheapest offer that is new and passes matching, with the seller name and a direct link.
- **Best price for a model** = the minimum of each active offer's latest valid observation.

## 4. Add-product flow (wizard)

1. The user enters a product name, which creates a `DiscoveryRun` job. The page polls via HTMX and shows progress live; the user can leave and come back.
2. **Ceneo first:** search Ceneo, collect variants (model codes, EAN, specs) and the shops listed for each model.
3. **Gemini fills gaps:** normalise model codes, add missing variants, and suggest URLs on supported shops (Google Search grounding, JSON schema output).
4. The user picks which **models** to observe.
5. For each chosen model, collect candidate offers on supported shops (from Ceneo's shop list, Gemini, and shop-specific lookups), and **check each candidate** by fetching it and running the matcher.
6. The user picks offers per model, and can **add URLs manually**. A URL from a shop without a shop class is **rejected** ("shop not supported yet").
7. Submit, and observation starts.

## 5. Model matching (every check for aggregators; discovery for all)

Steps, in order:
1. **Exact model code** in the title, specs or JSON-LD `mpn`/`sku`. Normalise case, spaces and dashes.
2. **EAN/GTIN**, if known for the model (from Ceneo/JSON-LD), compared with `gtin13`.
3. **Gemini**, for unclear cases only: give it the model's specs and the candidate's title and specs, and ask it to judge whether they match.
4. Still unclear: create a `MatchReview` (not counted in prices, shown in the summary).

Offer rules for v1: **new condition only** (exclude used, refurbished, outlet and ex-display "powystawowy" items). Shipping and stock are not filters.

## 6. Scraping

### Shop plugins
One Python class per shop, with shared helpers in a base class:

```python
class Shop(ABC):
    key: str                      # "xkom"
    domains: tuple[str, ...]      # ("x-kom.pl",)
    kind: Literal["single", "aggregator"]
    tiers: tuple[int, ...] = (1, 2, 3)   # fetch ladder to try, in order

    def fetch(self, url, tier) -> Page            # base impl: uses tier fetchers
    def parse(self, page) -> list[OfferData]       # price, currency, title, seller, condition, codes, ean
    def search(self, model) -> list[str]           # optional: candidate URLs for discovery
    def detect_block(self, page) -> str | None     # captcha/turnstile/blokada detection
```

- `BaseJsonLdShop` covers shops with schema.org Product/Offer data in a few lines each.
- Platform families share a base class: **x-kom + Neonet**, **Euro** (+ OleOle in v2), **Media Expert + Avans** (+ Electro in v2).
- Every shop has **tests against saved HTML fixtures** (`tests/fixtures/<shop>/*.html`).

### Fetch ladder & politeness
- Try tier 1, then 2, then 3, starting at the shop's lowest tier that has worked recently (each shop remembers the last tier that succeeded).
- **One global check interval** with **+/-20% jitter** per offer; requests to the **same shop are serialised and spaced** (random 5-20 s).
- Realistic headers (`Accept-Language: pl-PL`), cookies kept per shop, no parallel hits to the same shop.
- **Free only.** When every tier is blocked, record a `CheckFailure` and report it in the summary. No captcha solving.

### Failure handling
- If a tier fails, try the next tier in the same run.
- After **N failed runs in a row** (default 3), mark the offer `broken`; it stays in the summary until fixed or removed.
- An HTTP 404 or a removed listing is marked `gone` right away.

### Sanity guard
- If a new price differs from the model's **recent median by more than 40%**, mark the observation **suspicious**. It is not used for alerts and is flagged in the summary. This catches instalment prices like "2549,59 zł/mc", which the probe actually ran into.

## 7. Notifications

- **Alert:** sent when a model's best price falls below its **all-time low** (suspicious observations excluded). One email per model per new low: price, shop or seller, link, previous low.
- **Summary**, every `summary_interval_h`:
  - best current price per model with shop and link,
  - a **Problems** section: blocked or captcha'd checks, broken or gone offers, suspicious prices held back, pending match reviews,
  - **skipped** entirely when nothing changed and there are no problems.

## 8. Views

- Products list, then product detail (models, each model's offers, current best, all-time low, Chart.js price history per model and per offer).
- Add-product wizard (live progress page).
- Offer management: add a URL manually, pause or remove, see an offer's status and last failure.
- Match review queue.
- Settings page (intervals, email).
- Django admin as an escape hatch for raw CRUD.

## 9. Probe results (2026-11-23, from home IP)

Example URLs from SPEC.md, one fetch each:

| Shop | Tier 1 curl_cffi | Tier 2 Playwright+stealth | Notes |
|---|---|---|---|
| x-kom | OK JSON-LD (13 349) | - | model code in page |
| Neonet | OK JSON-LD (13 349) | - | same platform as x-kom (same product IDs) -> shared base |
| Morele | OK JSON-LD + GTIN | - | |
| Deluxury | OK JSON-LD Offer (12 498) | - | |
| TechLord | OK `itemprop=price` (12 499) | - | no JSON-LD; microdata |
| MediaMarkt | OK JSON-LD + GTIN | - | add-on Offers in JSON-LD (e.g. McAfee bundle), pick the main one |
| Empik | PARTIAL 200, price filled by JS | OK prices in DOM | tier 2 |
| Ceneo | BLOCKED JS challenge | OK JSON-LD, many shop prices | **critical for discovery**, tier 2 |
| Euro | BLOCKED "Blokada" 403 | OK JSON-LD | tier 2 |
| Media Expert | BLOCKED 403 challenge | OK JSON-LD | tier 2 |
| Avans | BLOCKED 403 challenge | OK JSON-LD | tier 2 |
| OleOle | BLOCKED "Blokada" 403 | BLOCKED 403 | Akamai Bot Manager (same as Euro). Tier 3: warm up on the homepage so Akamai's sensor script sets `_abck`/`bm_sz` cookies, then open the product page |
| Electro | BLOCKED 403 | BLOCKED "Cierpliwości..." | try tier 3 |
| Komputronik | BLOCKED Cloudflare | BLOCKED "Cierpliwości..." | try tier 3 |
| ASUS eStore | BLOCKED 403 | BLOCKED 403 | try tier 3 |
| Allegro | BLOCKED 403 (likely DataDome) | BLOCKED 403 | **DECIDED: use the official Allegro REST API** instead of scraping |

**Takeaways:** 6 shops work with plain HTTP, 5 more with a headless browser, and 5 are still blocked. The blocked five need a tier-3 experiment before we know if they're feasible for free. Allegro will use its official API (`api.allegro.pl`, free with app registration) instead of scraping.

## 10. Build order

1. (done) **Skeleton:** uv project, Django, docker-compose (web/worker/db), settings singleton, models + migrations, admin.
2. (done) **Fetch layer:** tier 1/2 fetchers, block detection, per-shop serialisation + jitter, fixture capture tool (`manage.py capture <url>`).
3. (done) **Easy shops first:** x-kom/Neonet, Morele, Deluxury, TechLord, MediaMarkt, with fixture tests.
4. (done) **Check loop:** scheduler, `PriceObservation`, failure handling, sanity guard.
5. (done) **Notifications:** all-time-low alert + summary email (Gmail SMTP).
6. (done) **UI:** product list/detail, charts, manual add offer, settings.
7. **Tier-2 shops:** Ceneo (single + aggregator), Euro, Media Expert/Avans, Empik.
8. **Matcher** (code -> EAN -> Gemini -> review) + **discovery wizard** (Ceneo -> Gemini).
9. *(v2)* **Allegro via official API** (aggregator shop class backed by REST, not scraping) + **tier-3 experiment** for OleOle, Electro, Komputronik, ASUS eStore.
10. Hardening: snapshot retention, logs, backups (`pg_dump`).

## 11. Open questions

- *(v2)* Allegro API: register an app at developer.allegro.pl; confirm which endpoints give offers + prices for a product (`/sale/products`, `/offers/listing`) and their auth/rate limits.
- *(v2)* Tier 3 needs a headed Chrome (an X display) inside Docker. Run that worker natively on the host instead?
- Gemini free-tier limits for grounding calls: check before step 8.
