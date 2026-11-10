
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

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True
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
