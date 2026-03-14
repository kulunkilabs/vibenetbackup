#!/bin/bash
# Auto-generate SECRET_KEY if using the default placeholder.
# Persists to /app/data/.secret_key so it survives container restarts.

PERSISTED_KEY="/app/data/.secret_key"

if [ "$SECRET_KEY" = "change-me-to-a-random-secret-key" ] || [ -z "$SECRET_KEY" ]; then
    if [ -f "$PERSISTED_KEY" ]; then
        export SECRET_KEY=$(cat "$PERSISTED_KEY")
    else
        export SECRET_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
        mkdir -p /app/data
        echo "$SECRET_KEY" > "$PERSISTED_KEY"
        chmod 600 "$PERSISTED_KEY"
        echo "[VIBENetBackup] Auto-generated SECRET_KEY (saved to $PERSISTED_KEY)"
    fi
fi

exec "$@"
