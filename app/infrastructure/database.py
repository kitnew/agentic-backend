from collections.abc import Generator
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from app.core.config import DatabaseSettings

settings = DatabaseSettings.from_env()
DATABASE_URL = settings.url

# SQLite-specific connection arguments (allow multi-threaded access)
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    echo=settings.echo,
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
    import app.infrastructure.models  # noqa: F401 - registers SQLAlchemy metadata
    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            connection.execute(text("SELECT pg_advisory_xact_lock(773144916)"))
            for migration in sorted((Path(__file__).parent / "migrations").glob("*.sql")):
                for statement in migration.read_text().split(";"):
                    if statement.strip():
                        connection.execute(text(statement))
            Base.metadata.create_all(bind=connection)
    else:
        Base.metadata.create_all(bind=engine)
        _ensure_sqlite_schema()


def _ensure_sqlite_schema() -> None:
    if not DATABASE_URL.startswith("sqlite"):
        return

    with engine.begin() as connection:
        conversation_columns = {
            row[1]
            for row in connection.execute(text("PRAGMA table_info(conversations)")).fetchall()
        }
        if "metadata" not in conversation_columns:
            connection.execute(text("ALTER TABLE conversations ADD COLUMN metadata JSON"))

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
