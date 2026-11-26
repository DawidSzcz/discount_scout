# discount_scout

A private, single-user price-drop watcher for Polish online shops. You add a
product (for example "Zenbook Duo"), pick the exact models you care about
(for example `UX8407AA-SN515X`), and the service checks a handful of offers a
few times a day. When a price drops it sends you an email; it also sends a
periodic summary of the lowest current price per product.

It runs locally (docker-compose, bound to 127.0.0.1) for one person. It does
not buy, sell, or store anyone else's data.

## How it works

- **Discovery:** models are found on Ceneo; offers are looked up on Ceneo
  first, then by searching the supported shops directly for anything Ceneo
  did not cover. You choose which offers to watch.
- **Checks:** each watched offer is fetched on a schedule (Procrastinate
  jobs), parsed (JSON-LD / microdata / per-shop parsers), and the model code
  is verified before a price is recorded. Every price is kept in the history.
- **Alerts:** an email on a new low price, plus summary emails every N hours.
  Prices of unavailable items never count.
- **Politeness:** requests to the same shop are spaced out, volumes are tiny
  (a few requests per offer per day), and results are cached in the database.

## Allegro integration

Allegro offers are read through the official Allegro REST API
(`api.allegro.pl`), not by scraping:

- Authentication: OAuth `client_credentials` (application token only; no
  user login, no access to any account data).
- Endpoint: `GET /offers/listing?product.id=<catalog product id>` to read the
  public offers of one catalog product and pick the cheapest that matches the
  watched model.
- Volume: a few calls per watched product per day.
- Read-only: the app never creates, edits or buys offers.

## Stack

Python 3.12 (uv), Django 5.2 + HTMX, Postgres 17, Procrastinate,
curl_cffi and Playwright for fetching, optional Gemini for grouping models
during discovery.

## Running it

```
cp .env.example .env        # fill in your own values
docker compose up -d        # UI on http://127.0.0.1:8000
uv run --env-file .env pytest -q
```

See `CLAUDE.md` for the day-to-day commands, `SPEC.md` for the original
requirements and `PLAN.md` for design decisions and per-shop findings.
