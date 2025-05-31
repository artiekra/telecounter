from sqlalchemy.ext.asyncio import (AsyncEngine, create_async_engine,
    AsyncSession, async_sessionmaker)
from sqlalchemy.orm import declarative_base
from sqlalchemy.engine.url import URL


def get_async_engine(database_url: str) -> AsyncEngine:
    """Return SQLAlchemy AsyncEngine object for the given database URL."""
    return create_async_engine(database_url, echo=False, future=True)


def get_session_maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create and return a sessionmaker for async SQLAlchemy sessions."""
    return async_sessionmaker(bind=engine, expire_on_commit=False)
