from sqlalchemy.engine import Engine
from sqlalchemy import create_engine


def get_engine(database_url: str) -> Engine:
    """Return SQLAlchemy Engine object for the given database URL."""
    engine = create_engine(database_url, echo=False, future=True)
    return engine
