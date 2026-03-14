#!/usr/bin/env bash
# VIBENetBackup Uninstaller
# Usage: curl -fsSL https://raw.githubusercontent.com/kulunkilabs/vibenetbackup/main/uninstall.sh | sudo bash
# Version: 1.2
set -euo pipefail

VERSION="1.2"

# ── Configuration ──────────────────────────────────────────────
INSTALL_DIR="${VIBENET_DIR:-/opt/vibenetbackup}"
SERVICE_USER="${VIBENET_USER:-vibenetbackup}"
SERVICE_NAME="vibenetbackup"

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
echo -e "${GREEN}║       VIBENetBackup Uninstaller              ║${NC}"
printf "${GREEN}║       Version: %-29s║${NC}\n" "${VERSION}"
echo -e "${GREEN}╚══════════════════════════════════════════════╝${NC}"
echo ""

# Must run as root
if [ "$(id -u)" -ne 0 ]; then
    fail "Please run as root: curl -fsSL <url> | sudo bash"
fi

# Check if installed
if [ ! -d "$INSTALL_DIR" ]; then
    fail "VIBENetBackup is not installed at $INSTALL_DIR"
fi

# ── Confirmation ───────────────────────────────────────────────
warn "This will remove VIBENetBackup from your system."
echo ""
echo -e "  Install directory: ${YELLOW}${INSTALL_DIR}${NC}"
echo -e "  Service user:      ${YELLOW}${SERVICE_USER}${NC}"
echo -e "  Database:          ${YELLOW}${INSTALL_DIR}/vibenetbackup.db${NC}"
echo -e "  Backups:           ${YELLOW}${INSTALL_DIR}/backups${NC}"
echo ""

# Ask about data removal
read -p "Keep backup data and database? [Y/n]: " KEEP_DATA
KEEP_DATA=${KEEP_DATA:-Y}

if [[ ! "$KEEP_DATA" =~ ^[Yy]$ ]]; then
    warn "All data including backups will be deleted!"
    read -p "Are you sure? Type 'yes' to confirm: " CONFIRM
    if [ "$CONFIRM" != "yes" ]; then
        info "Uninstall cancelled."
        exit 0
    fi
fi

echo ""
info "Starting uninstallation..."
echo ""

# ── Stop and disable service ───────────────────────────────────
if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
    info "Stopping ${SERVICE_NAME} service..."
    systemctl stop "$SERVICE_NAME" 2>/dev/null || true
    ok "Service stopped"
else
    info "Service not running"
fi

if systemctl is-enabled --quiet "$SERVICE_NAME" 2>/dev/null; then
    info "Disabling ${SERVICE_NAME} service..."
    systemctl disable "$SERVICE_NAME" 2>/dev/null || true
    ok "Service disabled"
fi

# ── Remove systemd service file ────────────────────────────────
if [ -f "/etc/systemd/system/${SERVICE_NAME}.service" ]; then
    info "Removing systemd service file..."
    rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
    systemctl daemon-reload
    ok "Service file removed"
fi

# ── Handle data and directory removal ──────────────────────────
if [[ "$KEEP_DATA" =~ ^[Yy]$ ]]; then
    # Keep data, only remove application code
    info "Preserving data in ${INSTALL_DIR}..."
    
    # Create a backup reminder
    cat > "${INSTALL_DIR}/README-UNINSTALLED.txt" <<EOF
VIBENetBackup has been uninstalled.

Your data is preserved in this directory:
  - Database: vibenetbackup.db
  - Backups:  backups/
  - Config:   .env

To completely remove this directory:
  sudo rm -rf ${INSTALL_DIR}

To reinstall:
  curl -fsSL https://raw.githubusercontent.com/kulunkilabs/vibenetbackup/main/install.sh | sudo bash
EOF
    ok "Data preserved. Note left at ${INSTALL_DIR}/README-UNINSTALLED.txt"
    
    # Remove everything except data
    find "$INSTALL_DIR" -mindepth 1 -maxdepth 1 ! -name 'vibenetbackup.db' ! -name 'backups' ! -name '.env' ! -name 'README-UNINSTALLED.txt' -exec rm -rf {} + 2>/dev/null || true
else
    # Remove everything
    info "Removing installation directory..."
    rm -rf "$INSTALL_DIR"
    ok "Directory removed"
fi

# ── Remove service user ────────────────────────────────────────
if id "$SERVICE_USER" &>/dev/null; then
    read -p "Remove service user '${SERVICE_USER}'? [y/N]: " REMOVE_USER
    REMOVE_USER=${REMOVE_USER:-N}
    
    if [[ "$REMOVE_USER" =~ ^[Yy]$ ]]; then
        info "Removing service user: ${SERVICE_USER}"
        userdel "$SERVICE_USER" 2>/dev/null || true
        ok "User removed"
    else
        warn "User '${SERVICE_USER}' preserved"
    fi
fi

# ── Done ───────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║     Uninstallation Complete!                 ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════╝${NC}"
echo ""

if [[ "$KEEP_DATA" =~ ^[Yy]$ ]]; then
    echo -e "  Data preserved at: ${BLUE}${INSTALL_DIR}${NC}"
    echo -e "  To remove later:   ${YELLOW}sudo rm -rf ${INSTALL_DIR}${NC}"
fi

echo -e "  To reinstall:      ${YELLOW}curl -fsSL https://raw.githubusercontent.com/kulunkilabs/vibenetbackup/main/install.sh | sudo bash${NC}"
echo ""
