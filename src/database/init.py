from sqlalchemy.engine import Engine
from .models import Base


def init_db(engine: Engine) -> None:
    """Create all tables in the database that do not yet exist."""
    Base.metadata.create_all(bind=engine)
