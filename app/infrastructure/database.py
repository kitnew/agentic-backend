import os
from collections.abc import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# Default to SQLite at start as requested: sqlite:///./test.db
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./test.db")

# SQLite-specific connection arguments (allow multi-threaded access)
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    echo=os.getenv("DB_ECHO", "false").lower() == "true",
)

# Session factory for database sessions
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

# SQLAlchemy 2.0 modern declarative base
class Base(DeclarativeBase):
    pass

def init_db() -> None:
    """
    Initialize the database by creating all tables registered on the Base metadata.
    """
    # Import all models here to register them with the metadata
    from app.infrastructure.models import ConversationModel, MessageModel, ToolCallModel
    Base.metadata.create_all(bind=engine)

def get_db() -> Generator[Session, None, None]:
    """
    Dependency generator function that yields a database session and ensures it is
    properly closed after use.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
