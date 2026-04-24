import logging
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from typing import Generator
from app.config import get_settings

logger = logging.getLogger("vibenetbackup")


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
    """Create all tables and apply schema migrations."""
    Base.metadata.create_all(bind=engine)
    _apply_migrations()
    _fix_orphaned_credential_refs()
    _check_secret_key_decrypts()


# ---------------------------------------------------------------------------
# Migration registry
# ---------------------------------------------------------------------------
# Each entry is (name, fn).  Migrations run in list order; each runs at most
# once, tracked by the _applied_migrations table.  To add a migration for a
# future release, append a new tuple — that's all.
#
# Rules for migration functions:
#   - Must be idempotent: check current state before changing anything.
#   - Must not rely on SQLAlchemy model definitions (models may change later).
#   - Use conn (SQLAlchemy Connection) for most DDL; use raw DBAPI only when
#     PRAGMA foreign_keys=OFF is required (table recreation with FK references).
# ---------------------------------------------------------------------------

def _apply_migrations() -> None:
    """Create migration tracking table, then run every pending migration in order."""
    with engine.connect() as conn:
        # --- Ensure tracking table exists (idempotent CREATE IF NOT EXISTS) ---
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS _applied_migrations (
                name       VARCHAR(100) NOT NULL PRIMARY KEY,
                applied_at DATETIME     NOT NULL DEFAULT (datetime('now'))
            )
        """))
        conn.commit()

        # Clean up any orphaned temp table from an interrupted migration
        conn.execute(text("DROP TABLE IF EXISTS credentials_new"))
        conn.commit()

        def is_applied(name: str) -> bool:
            return conn.execute(
                text("SELECT 1 FROM _applied_migrations WHERE name = :n"), {"n": name}
            ).fetchone() is not None

        def mark_applied(name: str) -> None:
            conn.execute(
                text("INSERT OR IGNORE INTO _applied_migrations (name) VALUES (:n)"),
                {"n": name},
            )
            conn.commit()

        # ── v09: credentials.group column ────────────────────────────────────
        if not is_applied("v09_credentials_group"):
            cols = {r[1] for r in conn.execute(text("PRAGMA table_info(credentials)")).fetchall()}
            if "group" not in cols:
                logger.info("Migration v09: adding credentials.group")
                conn.execute(text(
                    'ALTER TABLE credentials ADD COLUMN "group" VARCHAR(100) DEFAULT \'default\''
                ))
                conn.commit()
            mark_applied("v09_credentials_group")

        # ── v15: devices proxy columns ────────────────────────────────────────
        if not is_applied("v15_devices_proxy_columns"):
            cols = {r[1] for r in conn.execute(text("PRAGMA table_info(devices)")).fetchall()}
            for col_name, col_def in [
                ("proxy_host",          "VARCHAR(255)"),
                ("proxy_port",          "INTEGER"),
                ("proxy_credential_id", "INTEGER"),
            ]:
                if col_name not in cols:
                    logger.info("Migration v15: adding devices.%s", col_name)
                    conn.execute(text(f'ALTER TABLE devices ADD COLUMN "{col_name}" {col_def}'))
            conn.commit()
            mark_applied("v15_devices_proxy_columns")

        # ── v16: groups profile columns ───────────────────────────────────────
        if not is_applied("v16_groups_profile_columns"):
            tables = {r[0] for r in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()}
            if "groups" in tables:
                cols = {r[1] for r in conn.execute(text("PRAGMA table_info(groups)")).fetchall()}
                for col_name, col_def in [
                    ("destination_ids",  "TEXT"),
                    ("backup_engine",    "VARCHAR(50)"),
                    ("notification_ids", "TEXT"),
                ]:
                    if col_name not in cols:
                        logger.info("Migration v16: adding groups.%s", col_name)
                        conn.execute(text(f'ALTER TABLE groups ADD COLUMN "{col_name}" {col_def}'))
                conn.commit()
            mark_applied("v16_groups_profile_columns")

        # ── v161: credentials.username nullable ───────────────────────────────
        # SQLite cannot DROP NOT NULL via ALTER COLUMN; requires full table recreation.
        # PRAGMA foreign_keys=OFF is required before DROP TABLE when other tables
        # reference credentials — and it cannot be set inside an active transaction.
        # We commit first, then use the raw DBAPI connection directly.
        if not is_applied("v161_credentials_nullable"):
            col_info = {r[1]: r[3] for r in conn.execute(  # {name: notnull}
                text("PRAGMA table_info(credentials)")
            ).fetchall()}
            if col_info.get("username") == 1:  # notnull=1 → NOT NULL is set
                logger.info("Migration v161: making credentials.username nullable")
                conn.commit()
                raw = conn.connection.dbapi_connection
                raw.execute("PRAGMA foreign_keys=OFF")
                raw.execute("""
                    CREATE TABLE credentials_new (
                        id                      INTEGER      NOT NULL PRIMARY KEY,
                        name                    VARCHAR(255) NOT NULL UNIQUE,
                        username                VARCHAR(255),
                        password_encrypted      VARCHAR(500),
                        enable_secret_encrypted VARCHAR(500),
                        ssh_key_path            VARCHAR(500),
                        "group"                 VARCHAR(100) DEFAULT 'default',
                        created_at              DATETIME,
                        updated_at              DATETIME
                    )
                """)
                # Use explicit column names — never SELECT * — to avoid positional
                # mismatch when 'group' was added at the end by an earlier ALTER TABLE
                # (pre-v1.0 upgrade path) instead of at its model-definition position.
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
                # Must commit before returning connection to pool: the INSERT opened
                # an implicit sqlite3 transaction and pool reset calls rollback().
                raw.commit()
                raw.execute("PRAGMA foreign_keys=ON")
            mark_applied("v161_credentials_nullable")

        # ── v161_repair: fix column-swap data corruption ──────────────────────
        # Pre-v1.0 databases had 'group' appended at the end by ALTER TABLE.
        # The original v1.6.1 migration used SELECT * so positional mapping
        # put old group='default' into new updated_at (DATETIME), causing
        # "Invalid isoformat string: 'default'" on every credential load.
        if not is_applied("v161_repair_column_swap"):
            cols = {r[1] for r in conn.execute(text("PRAGMA table_info(credentials)")).fetchall()}
            if "updated_at" in cols:
                count = conn.execute(text(
                    "SELECT COUNT(*) FROM credentials WHERE updated_at = 'default'"
                )).scalar() or 0
                if count:
                    logger.warning(
                        "Migration v161_repair: fixing %d credential(s) with invalid "
                        "updated_at caused by v1.6.1 column-order mismatch", count,
                    )
                    conn.execute(text(
                        "UPDATE credentials SET updated_at = NULL WHERE updated_at = 'default'"
                    ))
                    # group holds the old created_at datetime string — reset to 'default'
                    conn.execute(text(
                        'UPDATE credentials SET "group" = \'default\' '
                        'WHERE "group" LIKE \'____-__-__%\''
                    ))
                    conn.commit()
            mark_applied("v161_repair_column_swap")

        # ── Add future migrations here ────────────────────────────────────────
        # Pattern:
        #
        #   if not is_applied("vXYZ_short_description"):
        #       # check schema state, apply only what's missing
        #       # ...
        #       mark_applied("vXYZ_short_description")
        #
        # Rules:
        #   • name must be unique and never reused
        #   • function must be idempotent (check before changing)
        #   • use explicit column names in any INSERT … SELECT
        #   • test with: old_db fixture (v0.8), v16_db fixture (v1.6), fresh DB


def _check_secret_key_decrypts() -> None:
    """Warn loudly at startup if existing encrypted data can't be decrypted with
    the current SECRET_KEY. Catches the #1 upgrade footgun: key loss / mismatch
    (deleted /app/data/.secret_key, regenerated .env, volume wipe, etc.).

    Probes one credential password + one notification channel URL. If either
    decrypt fails with InvalidToken, logs an actionable recovery message.
    Any other error is reported but silently — we don't want to block startup.
    """
    from cryptography.fernet import InvalidToken
    from app.models.credential import Credential
    from app.models.notification import NotificationChannel

    def _probe() -> str | None:
        with SessionLocal() as db:
            cred = db.query(Credential).filter(
                Credential.password_encrypted.isnot(None)
            ).first()
            if cred:
                try:
                    cred.get_password()
                except InvalidToken:
                    return "credentials"
                except Exception:
                    pass  # other errors aren't key-mismatch; ignore

            notif = db.query(NotificationChannel).filter(
                NotificationChannel.apprise_url_encrypted.isnot(None)
            ).first()
            if notif:
                try:
                    notif.get_url()
                except InvalidToken:
                    return "notifications"
                except Exception:
                    pass
        return None

    try:
        which = _probe()
    except Exception as e:
        logger.debug("SECRET_KEY self-test skipped: %s", e)
        return

    if which is None:
        return  # nothing to verify, or everything decrypts cleanly

    logger.warning(
        "═══════════════════════════════════════════════════════════════\n"
        "  SECRET_KEY MISMATCH — existing encrypted data cannot be decrypted.\n"
        "  The SECRET_KEY in your environment does not match the key that\n"
        "  encrypted data currently in the database (detected via %s).\n"
        "\n"
        "  Common causes:\n"
        "    - Docker:    /app/data/.secret_key was deleted or the data volume\n"
        "                 was wiped between container recreates\n"
        "    - Shell:     .env was regenerated and SECRET_KEY changed\n"
        "    - Migration: key was never copied when moving hosts\n"
        "\n"
        "  Recovery:\n"
        "    1. Restore the previous SECRET_KEY if you have a backup, OR\n"
        "    2. Clear + re-enter credentials / notifications via the UI:\n"
        "         /credentials   /notifications\n"
        "\n"
        "  Until one of those is done, backups that need encrypted credentials\n"
        "  will fail with empty error messages (str(InvalidToken) is '').\n"
        "═══════════════════════════════════════════════════════════════",
        which,
    )


def _fix_orphaned_credential_refs() -> None:
    """
    Clear device credential_id / proxy_credential_id that point to deleted credentials.
    Runs on every startup — safe because it only NULLs refs that would violate FK anyway.
    """
    with engine.connect() as conn:
        result = conn.execute(text(
            "UPDATE devices SET credential_id = NULL "
            "WHERE credential_id IS NOT NULL "
            "AND credential_id NOT IN (SELECT id FROM credentials)"
        ))
        if result.rowcount:
            logger.warning("Fixed %d device(s) with orphaned credential_id", result.rowcount)

        result = conn.execute(text(
            "UPDATE devices SET proxy_credential_id = NULL "
            "WHERE proxy_credential_id IS NOT NULL "
            "AND proxy_credential_id NOT IN (SELECT id FROM credentials)"
        ))
        if result.rowcount:
            logger.warning("Fixed %d device(s) with orphaned proxy_credential_id", result.rowcount)

        conn.commit()
