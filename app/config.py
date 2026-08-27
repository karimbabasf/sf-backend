from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, overridable via environment variables."""

    model_config = SettingsConfigDict(env_prefix="CONTACTS_", env_file=".env", extra="ignore")

    app_name: str = "Contacts API"

    # Defaults to an on-disk SQLite file so data survives a restart.
    # Point this at Postgres for a shared database.
    database_url: str = "sqlite:///./contacts.db"

    # Insert a few sample contacts on startup, skipped once the table has rows.
    seed_data: bool = True

    host: str = "127.0.0.1"
    port: int = 8000
    sql_echo: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
