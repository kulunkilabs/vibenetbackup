#!/usr/bin/env bash
# Secure file permissions for VIBENetBackup

set -e

echo "Setting secure file permissions..."

# Secure the database file
chmod 600 vibenetbackup.db 2>/dev/null || echo "Note: Database file not found or already secured"

# Secure the .env file (contains secrets)
chmod 600 .env

# Secure credential files
chmod 600 .env.example

# Backup directory should be accessible only to owner
chmod 700 backups

# App files readable but not writable by others
chmod -R go-rwx app/
chmod -R u+rwX app/

echo "Permissions secured!"
echo ""
echo "Current permissions:"
ls -la .env vibenetbackup.db 2>/dev/null || true
ls -ld backups/
