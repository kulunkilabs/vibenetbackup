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

exec "$@"
