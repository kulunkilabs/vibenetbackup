#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

# Kill any previous VIBENetBackup process on port 5005
OLD_PID=$(lsof -ti :5005 2>/dev/null || true)
if [ -n "$OLD_PID" ]; then
    echo "Stopping old process (PID $OLD_PID) on port 5005..."
    kill "$OLD_PID" 2>/dev/null || true
    sleep 1
fi

# Create venv if missing
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

source .venv/bin/activate

# Install/upgrade deps
pip install -q -r requirements.txt

# Copy .env from example if missing
if [ ! -f ".env" ]; then
    cp .env.example .env
    # Generate a real secret key
    python3 -c "from cryptography.fernet import Fernet; print(f'SECRET_KEY={Fernet.generate_key().decode()}')" >> .env
    echo "Created .env from template — edit it to configure your settings."
fi

echo ""
echo "  VIBENetBackup starting on http://0.0.0.0:5005"
echo ""

exec python -m app.main
