
import os
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

def normalize_database_url(database_url: str) -> str:
    """Normalize common hosted PostgreSQL URL schemes to psycopg 3."""
    parsed = urlsplit(database_url)
    scheme = parsed.scheme.lower()
    if scheme in {"postgres", "postgresql"}:
        return urlunsplit(("postgresql+psycopg", *parsed[1:]))
    if scheme == "postgresql+psycopg":
        return database_url
    raise RuntimeError(
        "DATABASE_URL must use postgres://, postgresql://, or "
        "postgresql+psycopg://."
    )


raw_database_url = os.getenv("DATABASE_URL")

if not raw_database_url:
    raise RuntimeError(
        "DATABASE_URL must be set to a PostgreSQL psycopg connection URL."
    )
DATABASE_URL = normalize_database_url(raw_database_url)

def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=max(1, _env_int("DB_POOL_SIZE", 5)),
    max_overflow=max(0, _env_int("DB_MAX_OVERFLOW", 10)),
    pool_timeout=max(1, _env_int("DB_POOL_TIMEOUT", 30)),
    pool_recycle=max(-1, _env_int("DB_POOL_RECYCLE", 1800)),
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
