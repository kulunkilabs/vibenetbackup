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

# Run database migrations on every startup so upgrades apply automatically.
# If the DB was created by create_all() (no alembic_version table), stamp it
# at the last known baseline revision so only new migrations are applied.
echo "[VIBENetBackup] Running database migrations..."
python3 - <<'PYEOF'
import os, sys, sqlite3

db_url = os.environ.get("DATABASE_URL", "sqlite:///./data/vibenetbackup.db")
if not db_url.startswith("sqlite"):
    sys.exit(0)  # PostgreSQL/MySQL handle alembic natively

db_path = db_url.replace("sqlite:////", "/").replace("sqlite:///", "")
if not os.path.exists(db_path):
    sys.exit(0)  # fresh DB — alembic will create everything

conn = sqlite3.connect(db_path)
cur = conn.cursor()
tables = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

if "alembic_version" not in tables and "devices" in tables:
    print("[VIBENetBackup] No alembic_version found — stamping existing DB at baseline b2c3d4e5f6g7")
    cur.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL CONSTRAINT alembic_version_pkc PRIMARY KEY)")
    cur.execute("INSERT INTO alembic_version VALUES ('b2c3d4e5f6g7')")
    conn.commit()

conn.close()
PYEOF

alembic upgrade head

exec "$@"
