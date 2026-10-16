# sf-backend

A Contacts REST API in FastAPI and SQLAlchemy that runs from one command, with no database server to set up.

Built at the **Roast My PR** event at GitHub HQ: a two-hour build judged on Qodo-reviewed pull requests, where it placed top 10. The UI is [sf-frontend](https://github.com/karimbabasf/sf-frontend). The write-up is [roast-my-pr](https://github.com/karimbabasf/roast-my-pr).

## How it works

- **Storage.** `CONTACTS_DATABASE_URL` defaults to `sqlite:///./contacts.db`, a file beside the process, so contacts survive a restart. The same code runs on Postgres (`postgresql+psycopg://...`).
- **Startup.** The lifespan hook runs `Base.metadata.create_all`, then seeds three sample contacts if the table is empty. `create_all` adds missing tables but never alters one, so after a model change, delete `contacts.db`.
- **Contacts.** `first_name`, `last_name` and `email` are required; email is unique, case-insensitive (`409` on a duplicate). Optional: `phone`, `photo`, `company`, `job_title`, `notes`, `addresses`.
- **Photos.** A base64 data URL, PNG, JPEG, WebP or GIF, up to 512 KB. The server decodes it and checks the file's magic bytes match the declared type, so a renamed file is rejected.
- **Addresses.** Their own table, foreign key to the contact with `ON DELETE CASCADE`. Up to 10 per contact; `type` (`Home`, `Work`, `Other`) and `street` are required. `PUT` and `PATCH` treat the list as a set: what you send replaces what was there.
- **Docs.** FastAPI builds the OpenAPI schema from the route signatures and Pydantic models, so `/docs`, `/redoc` and `/openapi.json` always match the code. Every endpoint documents its `404`, `409` and `422` responses.

## API

| Method | Path | What it does |
| --- | --- | --- |
| `GET` | `/health` | Liveness, database check, contact count |
| `GET` | `/` | Entry-point listing |
| `POST` | `/api/v1/contacts` | Create, `201` |
| `GET` | `/api/v1/contacts` | List: `search`, `limit` (1 to 200, default 50), `offset`, `sort_by`, `order` |
| `GET` | `/api/v1/contacts/{id}` | Fetch one |
| `PUT` | `/api/v1/contacts/{id}` | Full replace, omitted fields are cleared |
| `PATCH` | `/api/v1/contacts/{id}` | Partial update, only sent fields change |
| `DELETE` | `/api/v1/contacts/{id}` | Delete, `204` |

`search` is a case-insensitive substring match on name, email, company and phone. `sort_by` takes `id`, `first_name`, `last_name`, `email`, `company`, `created_at` or `updated_at`. Lists come back as `{ "items": [...], "total": 12, "limit": 50, "offset": 0 }`.

## Run

```bash
uv venv && uv pip install -e ".[dev]"     # or: python -m venv .venv && pip install -r requirements.txt
.venv/bin/python -m app.main              # or: .venv/bin/uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000/docs>. `GET /api/v1/contacts` returns the three seeded contacts.

```bash
curl -X POST http://127.0.0.1:8000/api/v1/contacts \
  -H 'content-type: application/json' \
  -d '{"first_name":"Katherine","last_name":"Johnson","email":"katherine@example.com","company":"NASA"}'

curl "http://127.0.0.1:8000/api/v1/contacts?search=nasa&sort_by=last_name"
```

For a throwaway database that empties on every boot:

```bash
CONTACTS_DATABASE_URL="sqlite+pysqlite:///:memory:" .venv/bin/python -m app.main
```

All settings are `CONTACTS_` environment variables (a `.env` file is read too):

| Variable | Default |
| --- | --- |
| `CONTACTS_DATABASE_URL` | `sqlite:///./contacts.db` |
| `CONTACTS_SEED_DATA` | `true` |
| `CONTACTS_HOST` | `127.0.0.1` |
| `CONTACTS_PORT` | `8000` |
| `CONTACTS_SQL_ECHO` | `false` |

## Test

```bash
.venv/bin/python -m pytest
```

Tests run through FastAPI's `TestClient` on their own empty in-memory database with seeding off (`tests/conftest.py`). `test_openapi.py` checks the published schema; `test_contacts_api.py` covers the endpoints.

## Layout

```
app/main.py             app, lifespan startup, /health and /
app/config.py           environment settings
app/database.py         engine, session factory, StaticPool wiring
app/models.py           Contact and Address ORM models
app/schemas.py          Pydantic request and response models, photo checks
app/crud.py             search, sort, paginate
app/seed.py             sample contacts for an empty database
app/routers/contacts.py REST endpoints
tests/                  API tests
```
