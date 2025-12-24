from sqlalchemy.ext.asyncio import (AsyncEngine, AsyncSession,
                                    async_sessionmaker, create_async_engine)


def get_async_engine(database_url: str) -> AsyncEngine:
    """Return SQLAlchemy AsyncEngine object for the given database URL."""
    return create_async_engine(database_url, echo=False, future=True)


def get_session_maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create and return a sessionmaker for async SQLAlchemy sessions."""
    return async_sessionmaker(bind=engine, expire_on_commit=False)
