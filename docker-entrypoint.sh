#!/bin/bash
# Apply timezone from TZ env var at runtime
if [ -n "$TZ" ] && [ -f "/usr/share/zoneinfo/$TZ" ]; then
    ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone
fi

# Ensure SECRET_KEY is persisted so credentials survive upgrades and docker pulls.
# Saves to /app/data/.secret_key (inside the mounted data volume).

PERSISTED_KEY="/app/data/.secret_key"
mkdir -p /app/data

if [ "$SECRET_KEY" = "change-me-to-a-random-secret-key" ] || [ "$SECRET_KEY" = "change-me" ] || [ -z "$SECRET_KEY" ]; then
    # No real key provided — load persisted or generate a new one
    if [ -f "$PERSISTED_KEY" ]; then
        export SECRET_KEY=$(cat "$PERSISTED_KEY")
    else
        export SECRET_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
        echo "$SECRET_KEY" > "$PERSISTED_KEY"
        chmod 600 "$PERSISTED_KEY"
        echo "[VIBENetBackup] Auto-generated SECRET_KEY (saved to $PERSISTED_KEY)"
    fi
else
    # User provided a custom SECRET_KEY — persist it so it's never lost
    if [ ! -f "$PERSISTED_KEY" ]; then
        echo "$SECRET_KEY" > "$PERSISTED_KEY"
        chmod 600 "$PERSISTED_KEY"
        echo "[VIBENetBackup] Persisted custom SECRET_KEY to $PERSISTED_KEY"
    elif [ "$(cat "$PERSISTED_KEY")" != "$SECRET_KEY" ]; then
        # Env key differs from persisted — use persisted to protect existing credentials
        echo "[VIBENetBackup] WARNING: SECRET_KEY in environment differs from persisted key."
        echo "[VIBENetBackup] Using persisted key to protect existing encrypted credentials."
        echo "[VIBENetBackup] To force a new key, delete $PERSISTED_KEY and re-enter all credentials."
        export SECRET_KEY=$(cat "$PERSISTED_KEY")
    fi
fi

# Apply any missing schema columns directly — safe to run on every startup.
# Uses sqlite3 directly so it works regardless of alembic_version state.
echo "[VIBENetBackup] Checking database schema..."
python3 - <<'PYEOF'
import os, sqlite3

db_url = os.environ.get("DATABASE_URL", "sqlite:///./data/vibenetbackup.db")
if not db_url.startswith("sqlite"):
    raise SystemExit(0)  # non-SQLite DBs handle migrations via alembic natively

db_path = db_url.replace("sqlite:////", "/").replace("sqlite:///", "")
if not os.path.exists(db_path):
    raise SystemExit(0)  # fresh DB — app startup will create all tables

conn = sqlite3.connect(db_path)
cur = conn.cursor()

existing = {r[1] for r in cur.execute("PRAGMA table_info(devices)").fetchall()}

migrations = [
    ("proxy_host",          "ALTER TABLE devices ADD COLUMN proxy_host VARCHAR(255)"),
    ("proxy_port",          "ALTER TABLE devices ADD COLUMN proxy_port INTEGER"),
    ("proxy_credential_id", "ALTER TABLE devices ADD COLUMN proxy_credential_id INTEGER"),
]

for col, sql in migrations:
    if col not in existing:
        print(f"[VIBENetBackup] Adding column: devices.{col}")
        cur.execute(sql)

conn.commit()
conn.close()
print("[VIBENetBackup] Schema up to date.")
PYEOF

exec "$@"
