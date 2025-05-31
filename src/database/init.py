from sqlalchemy.ext.asyncio import AsyncEngine
from .models import Base


async def init_db(engine: AsyncEngine) -> None:
    """Create all tables in the database that do not yet exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
