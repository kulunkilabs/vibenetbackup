"""
Tests for database migration logic in app/database.py.

Each test class simulates a specific upgrade scenario by constructing
a SQLite database with the "old" schema, then calling the migration
functions and asserting the schema/data afterwards.
"""

import sqlite3
import pytest
from sqlalchemy import create_engine, event, text
from unittest.mock import patch

from app.database import _apply_column_migrations, _fix_orphaned_credential_refs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_engine(db_path: str):
    """Create an engine with PRAGMA foreign_keys=ON, mirroring production setup."""
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_fk_pragma(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return engine


def get_columns(db_path: str, table: str) -> dict[str, int]:
    """Return {col_name: notnull} for a table via PRAGMA table_info."""
    conn = sqlite3.connect(db_path)
    result = {r[1]: r[3] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    conn.close()
    return result


def get_tables(db_path: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    conn.close()
    return tables


def get_indexes(db_path: str, table: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    indexes = {r[1] for r in conn.execute(f"PRAGMA index_list({table})").fetchall()}
    conn.close()
    return indexes


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def old_db(tmp_path):
    """
    v0.8-era database: credentials has username NOT NULL, no 'group' column;
    devices has no proxy columns; no groups table.
    """
    db_path = str(tmp_path / "vibenetbackup.db")
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE credentials (
            id                      INTEGER      NOT NULL PRIMARY KEY,
            name                    VARCHAR(255) NOT NULL UNIQUE,
            username                VARCHAR(255) NOT NULL,
            password_encrypted      VARCHAR(500),
            enable_secret_encrypted VARCHAR(500),
            ssh_key_path            VARCHAR(500),
            created_at              DATETIME,
            updated_at              DATETIME
        );
        CREATE TABLE devices (
            id           INTEGER      NOT NULL PRIMARY KEY,
            hostname     VARCHAR(255) NOT NULL,
            ip_address   VARCHAR(45)  NOT NULL,
            device_type  VARCHAR(50)  NOT NULL DEFAULT 'ruckus_fastiron',
            credential_id INTEGER REFERENCES credentials(id),
            "group"      VARCHAR(100) DEFAULT 'default',
            enabled      BOOLEAN      DEFAULT 1,
            backup_engine VARCHAR(50) NOT NULL DEFAULT 'netmiko',
            port         INTEGER      DEFAULT 22,
            notes        VARCHAR(1000),
            created_at   DATETIME,
            updated_at   DATETIME
        );
    """)
    conn.close()
    return db_path


@pytest.fixture
def v16_db(tmp_path):
    """
    v1.6-era database: all columns present, but credentials.username is still NOT NULL.
    Includes groups table (added in v1.6) without profile columns.
    """
    db_path = str(tmp_path / "vibenetbackup.db")
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE credentials (
            id                      INTEGER      NOT NULL PRIMARY KEY,
            name                    VARCHAR(255) NOT NULL UNIQUE,
            username                VARCHAR(255) NOT NULL,
            password_encrypted      VARCHAR(500),
            enable_secret_encrypted VARCHAR(500),
            ssh_key_path            VARCHAR(500),
            "group"                 VARCHAR(100) DEFAULT 'default',
            created_at              DATETIME,
            updated_at              DATETIME
        );
        CREATE TABLE devices (
            id                   INTEGER      NOT NULL PRIMARY KEY,
            hostname             VARCHAR(255) NOT NULL,
            ip_address           VARCHAR(45)  NOT NULL,
            device_type          VARCHAR(50)  NOT NULL DEFAULT 'ruckus_fastiron',
            credential_id        INTEGER REFERENCES credentials(id),
            "group"              VARCHAR(100) DEFAULT 'default',
            enabled              BOOLEAN      DEFAULT 1,
            backup_engine        VARCHAR(50)  NOT NULL DEFAULT 'netmiko',
            port                 INTEGER      DEFAULT 22,
            proxy_host           VARCHAR(255),
            proxy_port           INTEGER,
            proxy_credential_id  INTEGER REFERENCES credentials(id),
            notes                VARCHAR(1000),
            created_at           DATETIME,
            updated_at           DATETIME
        );
        CREATE TABLE groups (
            id   INTEGER      NOT NULL PRIMARY KEY,
            name VARCHAR(255) NOT NULL UNIQUE
        );
    """)
    conn.close()
    return db_path


@pytest.fixture
def current_db(tmp_path):
    """
    Fully-migrated v1.6.2 database schema with orphaned credential refs
    pre-inserted for _fix_orphaned_credential_refs tests.
    """
    db_path = str(tmp_path / "vibenetbackup.db")
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE credentials (
            id                      INTEGER      NOT NULL PRIMARY KEY,
            name                    VARCHAR(255) NOT NULL UNIQUE,
            username                VARCHAR(255),
            password_encrypted      VARCHAR(500),
            enable_secret_encrypted VARCHAR(500),
            ssh_key_path            VARCHAR(500),
            "group"                 VARCHAR(100) DEFAULT 'default',
            created_at              DATETIME,
            updated_at              DATETIME
        );
        CREATE TABLE devices (
            id                   INTEGER      NOT NULL PRIMARY KEY,
            hostname             VARCHAR(255) NOT NULL,
            ip_address           VARCHAR(45)  NOT NULL,
            device_type          VARCHAR(50)  NOT NULL DEFAULT 'ruckus_fastiron',
            credential_id        INTEGER REFERENCES credentials(id),
            "group"              VARCHAR(100) DEFAULT 'default',
            enabled              BOOLEAN      DEFAULT 1,
            backup_engine        VARCHAR(50)  NOT NULL DEFAULT 'netmiko',
            port                 INTEGER      DEFAULT 22,
            proxy_host           VARCHAR(255),
            proxy_port           INTEGER,
            proxy_credential_id  INTEGER REFERENCES credentials(id),
            notes                VARCHAR(1000),
            created_at           DATETIME,
            updated_at           DATETIME
        );
        PRAGMA foreign_keys=OFF;
        INSERT INTO devices (id, hostname, ip_address, device_type, credential_id, proxy_credential_id)
        VALUES (1, 'router1', '10.0.0.1', 'cisco_ios', 99, 99);
        PRAGMA foreign_keys=ON;
    """)
    conn.close()
    return db_path


# ---------------------------------------------------------------------------
# TestMigrationRecovery — interrupted migration leaves credentials_new behind
# ---------------------------------------------------------------------------

class TestMigrationRecovery:
    """App survives restart after a Docker upgrade killed a mid-flight migration."""

    def test_orphan_credentials_new_dropped_and_migration_completes(self, tmp_path):
        """
        Simulate: container killed after CREATE TABLE credentials_new but before
        RENAME. On next startup the orphan table must be dropped and the migration
        must complete successfully.
        """
        db_path = str(tmp_path / "vibenetbackup.db")
        conn = sqlite3.connect(db_path)
        conn.executescript("""
            CREATE TABLE credentials (
                id                      INTEGER      NOT NULL PRIMARY KEY,
                name                    VARCHAR(255) NOT NULL UNIQUE,
                username                VARCHAR(255) NOT NULL,
                password_encrypted      VARCHAR(500),
                enable_secret_encrypted VARCHAR(500),
                ssh_key_path            VARCHAR(500),
                "group"                 VARCHAR(100) DEFAULT 'default',
                created_at              DATETIME,
                updated_at              DATETIME
            );
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
            );
            CREATE TABLE devices (
                id                   INTEGER      NOT NULL PRIMARY KEY,
                hostname             VARCHAR(255) NOT NULL,
                ip_address           VARCHAR(45)  NOT NULL,
                device_type          VARCHAR(50)  NOT NULL DEFAULT 'ruckus_fastiron',
                credential_id        INTEGER REFERENCES credentials(id),
                "group"              VARCHAR(100) DEFAULT 'default',
                enabled              BOOLEAN      DEFAULT 1,
                backup_engine        VARCHAR(50)  NOT NULL DEFAULT 'netmiko',
                port                 INTEGER      DEFAULT 22,
                proxy_host           VARCHAR(255),
                proxy_port           INTEGER,
                proxy_credential_id  INTEGER REFERENCES credentials(id),
                notes                VARCHAR(1000),
                created_at           DATETIME,
                updated_at           DATETIME
            );
        """)
        conn.close()

        engine = make_engine(db_path)
        with patch("app.database.engine", engine):
            _apply_column_migrations()  # must not raise

        tables = get_tables(db_path)
        assert "credentials_new" not in tables, "orphan temp table should be removed"
        assert "credentials" in tables

        col_info = get_columns(db_path, "credentials")
        assert col_info["username"] == 0, "username should be nullable after migration"
        engine.dispose()

    def test_orphan_dropped_even_when_migration_already_done(self, tmp_path):
        """
        credentials_new exists but credentials.username is already nullable —
        orphan is still cleaned up without error.
        """
        db_path = str(tmp_path / "vibenetbackup.db")
        conn = sqlite3.connect(db_path)
        conn.executescript("""
            CREATE TABLE credentials (
                id       INTEGER      NOT NULL PRIMARY KEY,
                name     VARCHAR(255) NOT NULL UNIQUE,
                username VARCHAR(255),
                "group"  VARCHAR(100) DEFAULT 'default'
            );
            CREATE TABLE credentials_new (
                id       INTEGER      NOT NULL PRIMARY KEY,
                name     VARCHAR(255) NOT NULL UNIQUE,
                username VARCHAR(255)
            );
            CREATE TABLE devices (
                id            INTEGER      NOT NULL PRIMARY KEY,
                hostname      VARCHAR(255) NOT NULL,
                ip_address    VARCHAR(45)  NOT NULL,
                device_type   VARCHAR(50)  NOT NULL,
                credential_id INTEGER REFERENCES credentials(id),
                proxy_credential_id INTEGER REFERENCES credentials(id)
            );
        """)
        conn.close()

        engine = make_engine(db_path)
        with patch("app.database.engine", engine):
            _apply_column_migrations()

        assert "credentials_new" not in get_tables(db_path)
        engine.dispose()


# ---------------------------------------------------------------------------
# TestV09Migration — credentials.group column
# ---------------------------------------------------------------------------

class TestV09Migration:

    def test_group_column_added_to_credentials(self, old_db):
        engine = make_engine(old_db)
        with patch("app.database.engine", engine):
            _apply_column_migrations()
        engine.dispose()

        assert "group" in get_columns(old_db, "credentials")

    def test_group_column_not_duplicated_when_present(self, v16_db):
        """Second run must not raise 'duplicate column name'."""
        engine = make_engine(v16_db)
        with patch("app.database.engine", engine):
            _apply_column_migrations()
            _apply_column_migrations()
        engine.dispose()


# ---------------------------------------------------------------------------
# TestV15Migration — devices proxy columns
# ---------------------------------------------------------------------------

class TestV15Migration:

    def test_proxy_columns_added(self, old_db):
        engine = make_engine(old_db)
        with patch("app.database.engine", engine):
            _apply_column_migrations()
        engine.dispose()

        cols = get_columns(old_db, "devices")
        assert "proxy_host" in cols
        assert "proxy_port" in cols
        assert "proxy_credential_id" in cols

    def test_proxy_columns_not_duplicated_when_present(self, v16_db):
        engine = make_engine(v16_db)
        with patch("app.database.engine", engine):
            _apply_column_migrations()
            _apply_column_migrations()
        engine.dispose()


# ---------------------------------------------------------------------------
# TestV16Migration — groups profile columns
# ---------------------------------------------------------------------------

class TestV16Migration:

    def test_profile_columns_added_to_groups(self, v16_db):
        engine = make_engine(v16_db)
        with patch("app.database.engine", engine):
            _apply_column_migrations()
        engine.dispose()

        cols = get_columns(v16_db, "groups")
        assert "destination_ids" in cols
        assert "backup_engine" in cols
        assert "notification_ids" in cols

    def test_skipped_safely_when_groups_table_absent(self, old_db):
        """No groups table in old DBs — migration must not raise."""
        engine = make_engine(old_db)
        with patch("app.database.engine", engine):
            _apply_column_migrations()
        engine.dispose()

    def test_profile_columns_not_duplicated(self, v16_db):
        engine = make_engine(v16_db)
        with patch("app.database.engine", engine):
            _apply_column_migrations()
            _apply_column_migrations()
        engine.dispose()


# ---------------------------------------------------------------------------
# TestV161Migration — credentials.username nullable (table recreation with FKs)
# ---------------------------------------------------------------------------

class TestV161Migration:

    def test_username_becomes_nullable(self, v16_db):
        engine = make_engine(v16_db)
        with patch("app.database.engine", engine):
            _apply_column_migrations()
        engine.dispose()

        col_info = get_columns(v16_db, "credentials")
        assert col_info["username"] == 0, "username must be nullable (notnull=0)"

    def test_existing_rows_preserved(self, v16_db):
        """Data must survive the DROP + CREATE + INSERT + RENAME sequence."""
        conn = sqlite3.connect(v16_db)
        conn.execute(
            "INSERT INTO credentials (id, name, username) VALUES (1, 'cred1', 'admin')"
        )
        conn.commit()
        conn.close()

        engine = make_engine(v16_db)
        with patch("app.database.engine", engine):
            _apply_column_migrations()
        engine.dispose()

        conn = sqlite3.connect(v16_db)
        rows = conn.execute("SELECT id, name, username FROM credentials").fetchall()
        conn.close()
        assert rows == [(1, "cred1", "admin")]

    def test_fk_device_refs_intact_after_recreation(self, v16_db):
        """devices.credential_id must still point to the right credential row."""
        conn = sqlite3.connect(v16_db)
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(
            "INSERT INTO credentials (id, name, username) VALUES (1, 'cred1', 'admin')"
        )
        conn.execute(
            "INSERT INTO devices "
            "(id, hostname, ip_address, device_type, credential_id) "
            "VALUES (1, 'router1', '10.0.0.1', 'cisco_ios', 1)"
        )
        conn.commit()
        conn.close()

        engine = make_engine(v16_db)
        with patch("app.database.engine", engine):
            _apply_column_migrations()
        engine.dispose()

        conn = sqlite3.connect(v16_db)
        row = conn.execute(
            "SELECT d.credential_id FROM devices d WHERE d.id=1"
        ).fetchone()
        conn.close()
        assert row[0] == 1

    def test_proxy_credential_fk_intact_after_recreation(self, v16_db):
        """devices.proxy_credential_id also survives the table recreation."""
        conn = sqlite3.connect(v16_db)
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(
            "INSERT INTO credentials (id, name, username) VALUES (2, 'proxy-cred', 'proxyuser')"
        )
        conn.execute(
            "INSERT INTO devices "
            "(id, hostname, ip_address, device_type, proxy_credential_id) "
            "VALUES (1, 'router1', '10.0.0.1', 'cisco_ios', 2)"
        )
        conn.commit()
        conn.close()

        engine = make_engine(v16_db)
        with patch("app.database.engine", engine):
            _apply_column_migrations()
        engine.dispose()

        conn = sqlite3.connect(v16_db)
        row = conn.execute(
            "SELECT proxy_credential_id FROM devices WHERE id=1"
        ).fetchone()
        conn.close()
        assert row[0] == 2

    def test_index_recreated(self, v16_db):
        """ix_credentials_id index must exist after table recreation."""
        engine = make_engine(v16_db)
        with patch("app.database.engine", engine):
            _apply_column_migrations()
        engine.dispose()

        assert "ix_credentials_id" in get_indexes(v16_db, "credentials")

    def test_idempotent_on_already_nullable_db(self, v16_db):
        """Running migrations twice must not fail when username is already nullable."""
        engine = make_engine(v16_db)
        with patch("app.database.engine", engine):
            _apply_column_migrations()
            _apply_column_migrations()  # second run: no-op
        engine.dispose()

    def test_repair_column_swap_from_pre_v10_upgrade(self, tmp_path):
        """
        Regression: pre-v1.0 databases had 'group' added at the end via ALTER TABLE.
        The original v1.6.1 SELECT * INSERT mapped old group='default' into new
        updated_at (DATETIME), causing 'Invalid isoformat string: default' on load.
        The repair migration must detect and fix this silently.
        """
        db_path = str(tmp_path / "vibenetbackup.db")
        conn = sqlite3.connect(db_path)
        # Simulate the BROKEN post-v1.6.1 state:
        # updated_at holds 'default' (from the old group column)
        # group holds a datetime string (from the old created_at column)
        conn.executescript("""
            CREATE TABLE credentials (
                id                      INTEGER      NOT NULL PRIMARY KEY,
                name                    VARCHAR(255) NOT NULL UNIQUE,
                username                VARCHAR(255),
                password_encrypted      VARCHAR(500),
                enable_secret_encrypted VARCHAR(500),
                ssh_key_path            VARCHAR(500),
                "group"                 VARCHAR(100) DEFAULT 'default',
                created_at              DATETIME,
                updated_at              DATETIME
            );
            CREATE TABLE devices (
                id            INTEGER      NOT NULL PRIMARY KEY,
                hostname      VARCHAR(255) NOT NULL,
                ip_address    VARCHAR(45)  NOT NULL,
                device_type   VARCHAR(50)  NOT NULL,
                credential_id INTEGER REFERENCES credentials(id),
                proxy_host    VARCHAR(255),
                proxy_port    INTEGER,
                proxy_credential_id INTEGER REFERENCES credentials(id)
            );
            INSERT INTO credentials (id, name, username, "group", created_at, updated_at)
            VALUES
                (1, 'router-cred', 'admin', '2024-01-15 12:00:00.123456', '2024-01-15 12:00:00.123456', 'default'),
                (2, 'server-cred', 'root',  '2024-03-20 08:30:00',        '2024-03-20 08:30:00',        'default');
        """)
        conn.close()

        engine = make_engine(db_path)
        with patch("app.database.engine", engine):
            _apply_column_migrations()
        engine.dispose()

        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT name, \"group\", updated_at FROM credentials ORDER BY id"
        ).fetchall()
        conn.close()

        for name, group, updated_at in rows:
            assert updated_at is None, f"updated_at for {name!r} should be NULL, got {updated_at!r}"
            assert group == "default", f"group for {name!r} should be 'default', got {group!r}"

    def test_password_only_credential_can_be_inserted_after_migration(self, v16_db):
        """After migration, a credential with no username (password-only device) is valid."""
        engine = make_engine(v16_db)
        with patch("app.database.engine", engine):
            _apply_column_migrations()
        engine.dispose()

        conn = sqlite3.connect(v16_db)
        # Should not raise — username is now nullable
        conn.execute(
            "INSERT INTO credentials (id, name, username) VALUES (1, 'no-user-cred', NULL)"
        )
        conn.commit()
        row = conn.execute("SELECT username FROM credentials WHERE id=1").fetchone()
        conn.close()
        assert row[0] is None


# ---------------------------------------------------------------------------
# TestOrphanedCredentialFix — _fix_orphaned_credential_refs
# ---------------------------------------------------------------------------

class TestOrphanedCredentialFix:

    def test_orphaned_credential_id_nulled(self, current_db):
        engine = make_engine(current_db)
        with patch("app.database.engine", engine):
            _fix_orphaned_credential_refs()
        engine.dispose()

        conn = sqlite3.connect(current_db)
        row = conn.execute("SELECT credential_id FROM devices WHERE id=1").fetchone()
        conn.close()
        assert row[0] is None

    def test_orphaned_proxy_credential_id_nulled(self, current_db):
        engine = make_engine(current_db)
        with patch("app.database.engine", engine):
            _fix_orphaned_credential_refs()
        engine.dispose()

        conn = sqlite3.connect(current_db)
        row = conn.execute("SELECT proxy_credential_id FROM devices WHERE id=1").fetchone()
        conn.close()
        assert row[0] is None

    def test_valid_credential_ref_untouched(self, tmp_path):
        """A device pointing to an existing credential must not be modified."""
        db_path = str(tmp_path / "vibenetbackup.db")
        conn = sqlite3.connect(db_path)
        conn.executescript("""
            CREATE TABLE credentials (
                id       INTEGER      NOT NULL PRIMARY KEY,
                name     VARCHAR(255) NOT NULL UNIQUE,
                username VARCHAR(255)
            );
            CREATE TABLE devices (
                id                  INTEGER      NOT NULL PRIMARY KEY,
                hostname            VARCHAR(255) NOT NULL,
                ip_address          VARCHAR(45)  NOT NULL,
                device_type         VARCHAR(50)  NOT NULL,
                credential_id       INTEGER REFERENCES credentials(id),
                proxy_credential_id INTEGER REFERENCES credentials(id)
            );
            INSERT INTO credentials (id, name) VALUES (1, 'valid-cred');
            INSERT INTO devices (id, hostname, ip_address, device_type, credential_id)
            VALUES (1, 'router1', '10.0.0.1', 'cisco_ios', 1);
        """)
        conn.close()

        engine = make_engine(db_path)
        with patch("app.database.engine", engine):
            _fix_orphaned_credential_refs()
        engine.dispose()

        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT credential_id FROM devices WHERE id=1").fetchone()
        conn.close()
        assert row[0] == 1  # untouched

    def test_no_error_when_no_orphans(self, tmp_path):
        """Running with a clean DB (no orphans) must not raise."""
        db_path = str(tmp_path / "vibenetbackup.db")
        conn = sqlite3.connect(db_path)
        conn.executescript("""
            CREATE TABLE credentials (
                id INTEGER NOT NULL PRIMARY KEY,
                name VARCHAR(255) NOT NULL UNIQUE
            );
            CREATE TABLE devices (
                id                  INTEGER      NOT NULL PRIMARY KEY,
                hostname            VARCHAR(255) NOT NULL,
                ip_address          VARCHAR(45)  NOT NULL,
                device_type         VARCHAR(50)  NOT NULL,
                credential_id       INTEGER REFERENCES credentials(id),
                proxy_credential_id INTEGER REFERENCES credentials(id)
            );
        """)
        conn.close()

        engine = make_engine(db_path)
        with patch("app.database.engine", engine):
            _fix_orphaned_credential_refs()
        engine.dispose()
