import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import __version__
from app.config import get_settings
from app.crud import count_contacts
from app.database import engine, get_db, init_db
from app.routers import contacts
from app.schemas import HealthResponse, RootResponse
from app.seed import seed_if_empty

logger = logging.getLogger("contacts")
settings = get_settings()

API_DESCRIPTION = """
A self-contained REST API for storing people's basic contact information.

By default the service runs against an **SQLite file** beside the process, so no
external database is required — start the process and the API is ready. Contacts
survive a restart; set `CONTACTS_DATABASE_URL` to `sqlite+pysqlite:///:memory:`
for a throwaway database, or to a Postgres URL.

### Conventions

* All request and response bodies are JSON.
* Timestamps are ISO 8601 in UTC.
* Errors return `{"detail": "..."}`; request-validation failures (`422`) return
  FastAPI's standard `HTTPValidationError` shape.
* Collection responses are wrapped as `{items, total, limit, offset}` so clients
  can paginate.

### Interactive docs

* Swagger UI — [`/docs`](/docs)
* ReDoc — [`/redoc`](/redoc)
* Raw specification — [`/openapi.json`](/openapi.json)
"""

TAGS_METADATA = [
    {
        "name": "contacts",
        "description": (
            "Create, read, update, and delete contacts. Emails are unique across "
            "the collection, compared case-insensitively."
        ),
    },
    {
        "name": "meta",
        "description": "Service discovery and health checks. Useful for probes and smoke tests.",
    },
]


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    logger.info("database ready: %s", settings.database_url)
    if settings.seed_data:
        added = seed_if_empty()
        if added:
            logger.info("seeded %d sample contacts", added)
    yield
    engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    summary="Self-contained Contacts REST API backed by an SQLite file.",
    description=API_DESCRIPTION,
    openapi_tags=TAGS_METADATA,
    contact={"name": "sf-backend", "url": "https://github.com/David-Parry/sf-backend"},
    license_info={"name": "MIT", "identifier": "MIT"},
    servers=[{"url": "/", "description": "This server"}],
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(contacts.router)


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["meta"],
    operation_id="healthCheck",
    summary="Health check",
    response_description="Service status, active database dialect, and contact count.",
)
def health(db: Session = Depends(get_db)) -> HealthResponse:
    """
    Liveness probe that also proves the database is reachable.

    Issues a real `SELECT` against the configured database, so a `200` means the
    service can actually serve requests — not merely that the process is up.
    """
    db.execute(text("SELECT 1"))
    return HealthResponse(
        status="ok",
        database=engine.dialect.name,
        contacts=count_contacts(db),
    )


@app.get(
    "/",
    response_model=RootResponse,
    tags=["meta"],
    operation_id="getRoot",
    summary="Service discovery",
    response_description="Links to the docs, the specification, and the main collections.",
)
def root() -> RootResponse:
    """Return the paths a client needs to discover the rest of the API."""
    return RootResponse(
        name=settings.app_name,
        version=__version__,
        docs="/docs",
        redoc="/redoc",
        openapi="/openapi.json",
        contacts="/api/v1/contacts",
        health="/health",
    )


def run() -> None:
    """Entry point for `contacts-api` / `python -m app.main`."""
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    run()
