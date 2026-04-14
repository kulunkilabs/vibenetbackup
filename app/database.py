from sqlalchemy import create_engine, event
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


# Enable SQLite foreign key enforcement on every connection
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

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
    _fix_orphaned_credential_refs()


def _apply_column_migrations() -> None:
    """Add columns introduced in later versions to existing databases."""
    import logging
    logger = logging.getLogger("vibenetbackup")
    with engine.connect() as conn:
        from sqlalchemy import text, inspect
        # Clean up any temp tables left behind by interrupted migrations
        conn.execute(text("DROP TABLE IF EXISTS credentials_new"))
        conn.commit()
        inspector = inspect(conn)
        # v0.9: credentials.group column
        cred_cols = {c["name"] for c in inspector.get_columns("credentials")}
        if "group" not in cred_cols:
            conn.execute(text("ALTER TABLE credentials ADD COLUMN \"group\" VARCHAR(100) DEFAULT 'default'"))
            conn.commit()

        # v1.5: devices proxy columns (also handled by docker-entrypoint, duplicated here
        #        so bare-metal installs and the test client both pick them up)
        dev_cols = {c["name"] for c in inspector.get_columns("devices")}
        for col_name, col_def in [
            ("proxy_host",          "VARCHAR(255)"),
            ("proxy_port",          "INTEGER"),
            ("proxy_credential_id", "INTEGER"),
        ]:
            if col_name not in dev_cols:
                conn.execute(text(f'ALTER TABLE devices ADD COLUMN "{col_name}" {col_def}'))
        conn.commit()

        # v1.6: group profile columns
        if "groups" in inspector.get_table_names():
            group_cols = {c["name"] for c in inspector.get_columns("groups")}
            for col_name, col_def in [
                ("destination_ids", "TEXT"),        # JSON stored as TEXT in SQLite
                ("backup_engine", "VARCHAR(50)"),
                ("notification_ids", "TEXT"),
            ]:
                if col_name not in group_cols:
                    conn.execute(text(f'ALTER TABLE groups ADD COLUMN "{col_name}" {col_def}'))
            conn.commit()

        # v1.6.1: credentials.username — drop NOT NULL constraint so password-only
        # devices (no username) are supported. SQLite requires a full table recreation
        # to remove a NOT NULL constraint (ALTER COLUMN is not supported).
        # PRAGMA table_info columns: (cid, name, type, notnull, dflt_value, pk)
        cred_col_info = {r[1]: r[3] for r in conn.execute(text("PRAGMA table_info(credentials)")).fetchall()}
        if cred_col_info.get("username") == 1:  # notnull=1 means NOT NULL is set
            # SQLite requires a full table recreation to drop a NOT NULL constraint.
            # PRAGMA foreign_keys=OFF is needed to DROP the old credentials table
            # while devices still references it — but this pragma cannot be changed
            # inside an active transaction.  We commit any open SQLAlchemy transaction
            # first, then issue the DDL via the raw DBAPI (sqlite3) connection so
            # SQLAlchemy's autobegin cannot sneak a BEGIN in before the pragma.
            conn.commit()
            raw = conn.connection.dbapi_connection
            raw.execute("PRAGMA foreign_keys=OFF")
            raw.execute("""
                CREATE TABLE credentials_new (
                    id       INTEGER      NOT NULL PRIMARY KEY,
                    name     VARCHAR(255) NOT NULL UNIQUE,
                    username VARCHAR(255),
                    password_encrypted       VARCHAR(500),
                    enable_secret_encrypted  VARCHAR(500),
                    ssh_key_path             VARCHAR(500),
                    "group"  VARCHAR(100) DEFAULT 'default',
                    created_at DATETIME,
                    updated_at DATETIME
                )
            """)
            # Explicit column list avoids positional mismatch when the old table
            # had 'group' added at the end via ALTER TABLE (pre-v1.0 → v1.0 upgrade)
            # rather than at its model-definition position (before created_at/updated_at).
            raw.execute("""
                INSERT INTO credentials_new
                    (id, name, username, password_encrypted, enable_secret_encrypted,
                     ssh_key_path, "group", created_at, updated_at)
                SELECT id, name, username, password_encrypted, enable_secret_encrypted,
                       ssh_key_path, "group", created_at, updated_at
                FROM credentials
            """)
            raw.execute("DROP TABLE credentials")
            raw.execute("ALTER TABLE credentials_new RENAME TO credentials")
            raw.execute("CREATE INDEX IF NOT EXISTS ix_credentials_id ON credentials (id)")
            raw.commit()  # must commit: INSERT starts an implicit tx; pool reset calls rollback() otherwise
            raw.execute("PRAGMA foreign_keys=ON")

        # v1.6.1 data repair: databases upgraded from pre-v1.0 had 'group' appended
        # at the end by ALTER TABLE, so the v1.6.1 SELECT * INSERT misaligned columns:
        # old group='default' landed in new updated_at (DATETIME), and old created_at
        # (a datetime string) landed in new group (VARCHAR). This causes
        # "Invalid isoformat string: 'default'" on every credential load.
        # Detect and repair: updated_at='default' → NULL; group=datetime-like → 'default'
        cred_cols_now = {r[1] for r in conn.execute(text("PRAGMA table_info(credentials)")).fetchall()}
        invalid_count = 0
        if "updated_at" in cred_cols_now:
            invalid_count = conn.execute(text(
                "SELECT COUNT(*) FROM credentials WHERE updated_at = 'default'"
            )).scalar() or 0
        if invalid_count:
            logger.warning(
                "Repairing %d credential row(s) with invalid updated_at from v1.6.1 "
                "column-order mismatch — resetting updated_at=NULL and group='default'",
                invalid_count,
            )
            conn.execute(text(
                "UPDATE credentials SET updated_at = NULL WHERE updated_at = 'default'"
            ))
            # group now contains the old created_at datetime string (e.g. '2024-01-15 12:00:00')
            # Reset rows where group looks like a datetime (YYYY-MM-DD pattern)
            conn.execute(text(
                "UPDATE credentials SET \"group\" = 'default' "
                "WHERE \"group\" LIKE '____-__-__%'"
            ))
            conn.commit()


def _fix_orphaned_credential_refs() -> None:
    """Clear device credential_id / proxy_credential_id that point to deleted credentials."""
    import logging
    logger = logging.getLogger("vibenetbackup")
    with engine.connect() as conn:
        from sqlalchemy import text
        # Fix credential_id referencing non-existent credentials
        result = conn.execute(text(
            "UPDATE devices SET credential_id = NULL "
            "WHERE credential_id IS NOT NULL "
            "AND credential_id NOT IN (SELECT id FROM credentials)"
        ))
        if result.rowcount:
            logger.warning("Fixed %d device(s) with orphaned credential_id", result.rowcount)
        # Fix proxy_credential_id referencing non-existent credentials
        result = conn.execute(text(
            "UPDATE devices SET proxy_credential_id = NULL "
            "WHERE proxy_credential_id IS NOT NULL "
            "AND proxy_credential_id NOT IN (SELECT id FROM credentials)"
        ))
        if result.rowcount:
            logger.warning("Fixed %d device(s) with orphaned proxy_credential_id", result.rowcount)
        conn.commit()
