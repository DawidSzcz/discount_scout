# discount_scout

Price-drop watcher for Polish online shops. Requirements: `SPEC.md`. Decisions, data model, build order: `PLAN.md` (keep it updated when decisions change).

## Conventions
- Plain ASCII only in code, docs and messages (no emoji, arrows or fancy dashes); Polish letters are fine.
- Python 3.12 via `uv`; Django + HTMX; Postgres; Procrastinate for jobs.
- v1 is single-user, localhost, no login: use `scout.owner.get_owner()` wherever a user is needed.
- One Python class per shop; every shop needs fixture tests under `tests/fixtures/<shop>/`.

## Commands
- Start everything: `docker compose up -d` (web on http://127.0.0.1:8000, Postgres on 127.0.0.1:5432)
- Tests (needs db container running): `uv run --env-file .env pytest -q`
- Manage from host: `uv run --env-file .env python manage.py <cmd>`
- New migrations: `uv run --env-file .env python manage.py makemigrations scout`
