from sqlalchemy.orm import sessionmaker
from sqlalchemy.engine import Engine
from .models import Base


def get_session(engine: Engine):
    """Create and return a new SQLAlchemy session."""
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return SessionLocal()


def init_db(engine: Engine) -> None:
    """Create all tables in the database that do not yet exist."""
    Base.metadata.create_all(bind=engine)
