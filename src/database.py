import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session


def connect_to_db(database_url: str) -> Session:
    """Return SQLAlchemy Session object for the database."""
    engine = create_engine(database_url, echo=False, future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    return SessionLocal()
