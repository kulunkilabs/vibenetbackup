from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from typing import Generator
from app.config import get_settings


class Base(DeclarativeBase):
    pass


engine = create_engine(
    get_settings().DATABASE_URL,
    connect_args={"check_same_thread": False},  # SQLite only
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables and apply lightweight column migrations."""
    Base.metadata.create_all(bind=engine)
    _apply_column_migrations()


def _apply_column_migrations() -> None:
    """Add columns introduced in later versions to existing databases."""
    with engine.connect() as conn:
        from sqlalchemy import text, inspect
        inspector = inspect(conn)
        # v0.9: credentials.group column
        cred_cols = {c["name"] for c in inspector.get_columns("credentials")}
        if "group" not in cred_cols:
            conn.execute(text("ALTER TABLE credentials ADD COLUMN \"group\" VARCHAR(100) DEFAULT 'default'"))
            conn.commit()
