# discount_scout

Price-drop watcher for Polish online shops. Requirements: `SPEC.md`. Decisions, data model, build order: `PLAN.md` (keep it updated when decisions change).

## Conventions
- Plain ASCII only in code, docs and messages (no emoji, arrows or fancy dashes); Polish letters are fine.
- Python 3.12 via `uv`; Django + HTMX; Postgres; Procrastinate for jobs.
- v1 is single-user, localhost, no login: use `scout.owner.get_owner()` wherever a user is needed.
- UI: server-rendered Django templates + HTMX for row actions; htmx and Chart.js are vendored in `scout/static/scout/vendor/` (no CDN).
- Gemini (`scout/llm.py`) is used only in discovery, never in price checks; tests blank `GEMINI_API_KEY` so they never call the API.
- One Python class per shop; every shop needs fixture tests under `tests/fixtures/<shop>/`.

## Commands
- Start everything: `docker compose up -d` (UI on http://127.0.0.1:8000, admin on /admin/, Postgres on 127.0.0.1:5432)
- Tests (needs db container running): `uv run --env-file .env pytest -q`
- Manage from host: `uv run --env-file .env python manage.py <cmd>`
- New migrations: `uv run --env-file .env python manage.py makemigrations scout`, then `docker compose up -d` (re-runs the `migrate` service)
- The worker does not auto-reload: `docker compose restart worker` after changing task/check/shop code
- Try a shop URL live (no DB writes): `uv run --env-file .env python manage.py try_url <url>`
- Check offers now, bypassing the queue: `... manage.py check_now --offer <id> | --due | --all`
- Save a page as a test fixture: `... manage.py capture <url> --shop <key> [--tier 2]`
