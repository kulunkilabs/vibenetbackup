#!/usr/bin/env bash
# VIBENetBackup Installer
# Usage: curl -fsSL https://raw.githubusercontent.com/kulunkilabs/vibenetbackup/main/install.sh | sudo bash
# Version: 1.3
set -euo pipefail

VERSION="1.3"

# ── Configuration ──────────────────────────────────────────────
REPO_URL="${VIBENET_REPO:-https://github.com/kulunkilabs/vibenetbackup.git}"
INSTALL_DIR="${VIBENET_DIR:-/opt/vibenetbackup}"
SERVICE_USER="${VIBENET_USER:-vibenetbackup}"
PORT="${VIBENET_PORT:-5005}"
BRANCH="${VIBENET_BRANCH:-main}"


# ── Colors ─────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $*"; exit 1; }

# ── Pre-flight checks ─────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║       VIBENetBackup Installer                ║${NC}"
printf "${GREEN}║       Version: %-29s║${NC}\n" "${VERSION}"
echo -e "${GREEN}╚══════════════════════════════════════════════╝${NC}"
echo ""

# Must run as root
if [ "$(id -u)" -ne 0 ]; then
    fail "Please run as root: curl -fsSL <url> | sudo bash"
fi

# Check OS
if [ ! -f /etc/os-release ]; then
    fail "Unsupported OS — requires a Linux distribution with systemd"
fi
. /etc/os-release
info "Detected OS: $PRETTY_NAME"

# ── Install system dependencies ────────────────────────────────
info "Installing system dependencies..."

if command -v apt-get &>/dev/null; then
    apt-get update -qq
    apt-get install -y -qq python3 python3-venv python3-pip git curl >/dev/null 2>&1
elif command -v dnf &>/dev/null; then
    dnf install -y -q python3 python3-pip git curl >/dev/null 2>&1
elif command -v yum &>/dev/null; then
    yum install -y -q python3 python3-pip git curl >/dev/null 2>&1
elif command -v pacman &>/dev/null; then
    pacman -Sy --noconfirm python python-pip git curl >/dev/null 2>&1
else
    warn "Could not detect package manager — ensure python3, pip, git are installed"
fi

# Verify Python 3.11+
PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)
if [ -z "$PYTHON_VERSION" ]; then
    fail "Python 3 is not installed"
fi
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)
if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 11 ]; }; then
    fail "Python 3.11+ required (found $PYTHON_VERSION)"
fi
ok "Python $PYTHON_VERSION"

# Verify git
command -v git &>/dev/null || fail "git is not installed"
ok "git $(git --version | awk '{print $3}')"

# ── Create service user ────────────────────────────────────────
if ! id "$SERVICE_USER" &>/dev/null; then
    info "Creating service user: $SERVICE_USER"
    useradd -r -s /usr/sbin/nologin -m -d "$INSTALL_DIR" "$SERVICE_USER"
    ok "User $SERVICE_USER created"
else
    ok "User $SERVICE_USER exists"
fi

# ── Preserve existing data before any changes ─────────────────
SAFE_DIR=$(mktemp -d /tmp/vibenetbackup-safe.XXXXXX)

if [ -f "$INSTALL_DIR/.env" ]; then
    cp "$INSTALL_DIR/.env" "$SAFE_DIR/.env"
    warn "Existing .env saved — SECRET_KEY and credentials will be preserved"
fi
if [ -f "$INSTALL_DIR/vibenetbackup.db" ]; then
    cp "$INSTALL_DIR/vibenetbackup.db" "$SAFE_DIR/vibenetbackup.db"
    warn "Existing database saved"
fi
if [ -d "$INSTALL_DIR/backups" ] && [ "$(ls -A "$INSTALL_DIR/backups" 2>/dev/null)" ]; then
    cp -r "$INSTALL_DIR/backups" "$SAFE_DIR/backups"
    warn "Existing backups saved"
fi
if [ -d "$INSTALL_DIR/ssh_keys" ] && [ "$(ls -A "$INSTALL_DIR/ssh_keys" 2>/dev/null)" ]; then
    cp -r "$INSTALL_DIR/ssh_keys" "$SAFE_DIR/ssh_keys"
    warn "Existing SSH keys saved"
fi

# ── Clone / update repository ─────────────────────────────────
if [ -d "$INSTALL_DIR/.git" ]; then
    info "Updating existing installation..."
    cd "$INSTALL_DIR"
    chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
    sudo -u "$SERVICE_USER" git fetch origin
    sudo -u "$SERVICE_USER" git reset --hard "origin/$BRANCH"
    ok "Updated to latest"
else
    # Remove old directory if it exists (data already safe)
    if [ -d "$INSTALL_DIR" ]; then
        rm -rf "$INSTALL_DIR"
    fi

    info "Cloning repository..."
    git clone -b "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
    chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
    ok "Cloned to $INSTALL_DIR"
fi

cd "$INSTALL_DIR"

# ── Restore preserved data ────────────────────────────────────
if [ -f "$SAFE_DIR/.env" ]; then
    cp "$SAFE_DIR/.env" .env
    chown "$SERVICE_USER:$SERVICE_USER" .env
    chmod 600 .env
    ok "Configuration restored (SECRET_KEY preserved)"
fi
if [ -f "$SAFE_DIR/vibenetbackup.db" ]; then
    cp "$SAFE_DIR/vibenetbackup.db" vibenetbackup.db
    chown "$SERVICE_USER:$SERVICE_USER" vibenetbackup.db
    chmod 600 vibenetbackup.db
    ok "Database restored"
fi
if [ -d "$SAFE_DIR/backups" ]; then
    rm -rf backups
    cp -r "$SAFE_DIR/backups" backups
    chown -R "$SERVICE_USER:$SERVICE_USER" backups
    ok "Backups restored"
fi
if [ -d "$SAFE_DIR/ssh_keys" ]; then
    rm -rf ssh_keys
    cp -r "$SAFE_DIR/ssh_keys" ssh_keys
    chown -R "$SERVICE_USER:$SERVICE_USER" ssh_keys
    chmod 700 ssh_keys
    ok "SSH keys restored"
fi

rm -rf "$SAFE_DIR"

cd "$INSTALL_DIR"

# Ensure correct ownership before any service-user operations
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

# ── Python virtual environment ─────────────────────────────────
info "Setting up Python virtual environment..."
if [ ! -d ".venv" ]; then
    sudo -u "$SERVICE_USER" python3 -m venv .venv
fi
sudo -u "$SERVICE_USER" .venv/bin/pip install -q --upgrade pip >/dev/null 2>&1
sudo -u "$SERVICE_USER" .venv/bin/pip install -q -r requirements.txt >/dev/null 2>&1
ok "Dependencies installed"

# ── Generate .env configuration ────────────────────────────────
if [ ! -f ".env" ]; then
    info "Generating configuration..."
    SECRET_KEY=$(.venv/bin/python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
    AUTH_PASS=$(openssl rand -base64 16 | tr -d '=/+' | head -c 20)

    # Get server IP for CORS (auto-detected)
    SERVER_IP=$(hostname -I | awk '{print $1}')
    if [ -n "$SERVER_IP" ]; then
        info "Detected server IP: ${SERVER_IP}"
        CORS_LINE="http://localhost:${PORT},http://127.0.0.1:${PORT},http://0.0.0.0:${PORT},http://${SERVER_IP}:${PORT}"
    else
        warn "Could not detect server IP, using default CORS"
        CORS_LINE="http://localhost:${PORT},http://127.0.0.1:${PORT},http://0.0.0.0:${PORT}"
    fi
    
    cat > .env <<EOF
DATABASE_URL=sqlite:///./vibenetbackup.db
SECRET_KEY=${SECRET_KEY}
BACKUP_DIR=./backups
OXIDIZED_URL=http://localhost:8888
LOG_LEVEL=INFO
HOST=0.0.0.0
PORT=${PORT}
AUTH_USERNAME=admin
AUTH_PASSWORD=${AUTH_PASS}

# CORS - comma-separated list of allowed origins
# Auto-detected IP: ${SERVER_IP:-none}
# Secure (localhost only): http://localhost:${PORT},http://127.0.0.1:${PORT}
# Wide range (allows any origin): *
# Wide range (private networks): http://localhost:${PORT},http://127.0.0.1:${PORT},http://0.0.0.0:${PORT},http://192.168.0.0/16,http://10.0.0.0/8,http://172.16.0.0/12
CORS_ORIGINS=${CORS_LINE}
EOF

    chown "$SERVICE_USER:$SERVICE_USER" .env
    chmod 600 .env
    ok "Configuration generated"
    echo ""
    warn "Your login credentials:"
    echo -e "   Username: ${GREEN}admin${NC}"
    echo -e "   Password: ${GREEN}${AUTH_PASS}${NC}"
    warn "Save these now — the password is not shown again."
    echo ""
else
    ok "Configuration exists (keeping current .env)"
fi

# ── Create directories ─────────────────────────────────────────
sudo -u "$SERVICE_USER" mkdir -p "$INSTALL_DIR/backups"
sudo -u "$SERVICE_USER" mkdir -p -m 700 "$INSTALL_DIR/ssh_keys"

# ── Create systemd service ─────────────────────────────────────
info "Creating systemd service..."

cat > /etc/systemd/system/vibenetbackup.service <<EOF
[Unit]
Description=VIBENetBackup - Network Device Configuration Backup Manager
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_USER}
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/.venv/bin/python -m app.main
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=${INSTALL_DIR}
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable vibenetbackup >/dev/null 2>&1
systemctl restart vibenetbackup
ok "Service installed and started"

# ── Wait and verify ────────────────────────────────────────────
info "Waiting for startup..."
sleep 3
if systemctl is-active --quiet vibenetbackup; then
    ok "VIBENetBackup is running"
else
    warn "Service may still be starting — check: journalctl -u vibenetbackup -f"
fi

# ── Done ───────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║     Installation Complete!                   ║${NC}"
printf "${GREEN}║     Version: %-31s║${NC}\n" "${VERSION}"
echo -e "${GREEN}╚══════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  Web UI:    ${BLUE}http://$(hostname -I | awk '{print $1}'):${PORT}${NC}"
echo -e "  Install:   ${INSTALL_DIR}"
echo -e "  Config:    ${INSTALL_DIR}/.env"
echo -e "  Logs:      journalctl -u vibenetbackup -f"
echo -e "  Service:   systemctl {start|stop|restart|status} vibenetbackup"
echo ""
echo -e "  ${YELLOW}Management:${NC}"
echo -e "    Show password:  ${INSTALL_DIR}/manage.sh show-password"
echo -e "    Change password: ${INSTALL_DIR}/manage.sh set-password"
echo -e "    Service status: ${INSTALL_DIR}/manage.sh status"
echo ""
echo -e "  To update: curl -fsSL https://raw.githubusercontent.com/kulunkilabs/vibenetbackup/main/install.sh | sudo bash"
echo ""
