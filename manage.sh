#!/usr/bin/env bash
# VIBENetBackup Management Script
# Usage: ./manage.sh [show-password|set-password|reset-password|status|logs]
set -euo pipefail

INSTALL_DIR="${VIBENET_DIR:-/opt/vibenetbackup}"
ENV_FILE="$INSTALL_DIR/.env"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $*"; exit 1; }

show_help() {
    echo "VIBENetBackup Management Script"
    echo ""
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  show-password     Show current admin password"
    echo "  set-password      Change admin password interactively"
    echo "  reset-password    Generate new random password"
    echo "  status            Show service status"
    echo "  logs              Show service logs"
    echo "  help              Show this help"
    echo ""
}

show_password() {
    if [ ! -f "$ENV_FILE" ]; then
        fail ".env file not found at $ENV_FILE"
    fi
    
    USERNAME=$(grep "^AUTH_USERNAME=" "$ENV_FILE" | cut -d= -f2)
    PASSWORD=$(grep "^AUTH_PASSWORD=" "$ENV_FILE" | cut -d= -f2)
    
    echo ""
    echo -e "${GREEN}Current Credentials:${NC}"
    echo -e "  Username: ${GREEN}$USERNAME${NC}"
    echo -e "  Password: ${GREEN}$PASSWORD${NC}"
    echo ""
    warn "Keep this password secure!"
}

set_password() {
    if [ ! -f "$ENV_FILE" ]; then
        fail ".env file not found at $ENV_FILE"
    fi
    
    echo ""
    echo -e "${GREEN}Change Admin Password${NC}"
    echo ""
    
    read -s -p "Enter new password: " NEW_PASS
    echo ""
    read -s -p "Confirm new password: " CONFIRM_PASS
    echo ""
    
    if [ "$NEW_PASS" != "$CONFIRM_PASS" ]; then
        fail "Passwords do not match!"
    fi
    
    if [ -z "$NEW_PASS" ]; then
        fail "Password cannot be empty!"
    fi
    
    # Update .env file
    sed -i "s/^AUTH_PASSWORD=.*/AUTH_PASSWORD=$NEW_PASS/" "$ENV_FILE"
    
    # Restart service if running
    if systemctl is-active --quiet vibenetbackup 2>/dev/null; then
        info "Restarting service..."
        systemctl restart vibenetbackup
        ok "Service restarted"
    fi
    
    ok "Password changed successfully!"
    echo ""
    echo -e "New credentials:"
    echo -e "  Username: ${GREEN}admin${NC}"
    echo -e "  Password: ${GREEN}$NEW_PASS${NC}"
}

reset_password() {
    if [ ! -f "$ENV_FILE" ]; then
        fail ".env file not found at $ENV_FILE"
    fi
    
    echo ""
    read -p "Generate new random password? [y/N]: " CONFIRM
    
    if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
        info "Cancelled"
        exit 0
    fi
    
    NEW_PASS=$(openssl rand -base64 16 | tr -d '=/+' | head -c 20)
    
    # Update .env file
    sed -i "s/^AUTH_PASSWORD=.*/AUTH_PASSWORD=$NEW_PASS/" "$ENV_FILE"
    
    # Restart service if running
    if systemctl is-active --quiet vibenetbackup 2>/dev/null; then
        info "Restarting service..."
        systemctl restart vibenetbackup
        ok "Service restarted"
    fi
    
    echo ""
    ok "New password generated!"
    echo ""
    echo -e "${GREEN}New Credentials:${NC}"
    echo -e "  Username: ${GREEN}admin${NC}"
    echo -e "  Password: ${GREEN}$NEW_PASS${NC}"
    echo ""
    warn "Save this password now — it won't be shown again!"
}

show_status() {
    echo ""
    echo -e "${GREEN}VIBENetBackup Status${NC}"
    echo ""
    
    if systemctl is-active --quiet vibenetbackup 2>/dev/null; then
        echo -e "  Service: ${GREEN}Running${NC}"
    else
        echo -e "  Service: ${RED}Stopped${NC}"
    fi
    
    if systemctl is-enabled --quiet vibenetbackup 2>/dev/null; then
        echo -e "  Autostart: ${GREEN}Enabled${NC}"
    else
        echo -e "  Autostart: ${YELLOW}Disabled${NC}"
    fi
    
    PORT=$(grep "^PORT=" "$ENV_FILE" 2>/dev/null | cut -d= -f2 || echo "5005")
    echo -e "  Port: ${BLUE}$PORT${NC}"
    
    IP=$(hostname -I | awk '{print $1}')
    echo -e "  Access: ${BLUE}http://$IP:$PORT${NC}"
    echo ""
}

show_logs() {
    echo ""
    info "Showing logs (Ctrl+C to exit)..."
    echo ""
    journalctl -u vibenetbackup -f
}

# Main
case "${1:-help}" in
    show-password)
        show_password
        ;;
    set-password)
        set_password
        ;;
    reset-password)
        reset_password
        ;;
    status)
        show_status
        ;;
    logs)
        show_logs
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        fail "Unknown command: $1. Use 'help' for usage."
        ;;
esac
