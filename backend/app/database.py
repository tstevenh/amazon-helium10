"""
SQLAlchemy engine, session factory, declarative base, and the get_db FastAPI dependency.

Sync engine (psycopg2) is used deliberately for Sprint 1A — simpler failure modes than async
SQLAlchemy, and Sprint 1A has no concurrency requirements that justify the added complexity.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    future=True,
    connect_args={
        "options": "-c statement_timeout=30000 -c lock_timeout=10000",
    },
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
