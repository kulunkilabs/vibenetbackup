# Configuration

All settings are configured via environment variables in `.env` (or in the `environment` section of `docker-compose.yml` for Docker).

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./vibenetbackup.db` | Database connection string |
| `SECRET_KEY` | `change-me` | Encryption key for stored credentials |
| `AUTH_USERNAME` | `admin` | Web UI / API username |
| `AUTH_PASSWORD` | `admin` | Web UI / API password |
| `HOST` | `0.0.0.0` | Listen address |
| `PORT` | `5005` | Listen port |
| `CORS_ORIGINS` | `http://localhost:5005,...` | Comma-separated allowed origins |
| `BACKUP_DIR` | `./backups` | Where backup files are stored |
| `OXIDIZED_URL` | `http://localhost:8888` | Oxidized REST API URL |
| `LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `TZ` | `America/Chicago` | Container timezone (e.g. `America/New_York`, `Europe/London`) |

---

## SECRET_KEY

The `SECRET_KEY` encrypts credential passwords stored in the database using Fernet symmetric encryption. Any string works — it is derived into a valid key via SHA-256.

**Important:**
- Use a long, random string in production
- Must remain the same across restarts — changing it makes existing encrypted credentials unreadable
- The install scripts auto-generate a random key if not set
- Docker auto-generates and persists a key in `/app/data/.secret_key`

**Generate a secure key:**
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
# or
openssl rand -base64 32
```

> **Warning:** If you change `SECRET_KEY` after credentials have been saved, all stored passwords become undecryptable. You will need to re-enter them.

---

## Getting Started

1. **Login** — Use credentials from installation output (or defaults for development)
2. **Credentials** — Add SSH credentials for your devices (username + password or SSH key)
3. **Devices** — Add devices manually or import from Oxidized
4. **Test** — Click **Test All** to verify connectivity
5. **Destinations** — Configure where backups are stored (local, Git, SMB); enable compression if desired
6. **Schedule** — Create backup jobs with cron expressions
7. **Retention** — Configure GFS retention policies per destination
8. **Notifications** — Add Apprise notification channels for backup alerts

---

## Notifications (Apprise)

VIBENetBackup uses [Apprise](https://github.com/caronc/apprise) for notifications. Configure channels at **Notifications** in the web UI.

Each channel has:
- **Apprise URL** — encrypted in the database (Fernet)
- **On Success / On Failure** — choose when to notify
- **Test button** — verify delivery before relying on it

### Email Examples

| Scenario | Apprise URL |
|----------|-------------|
| **Gmail** (app password) | `mailto://user:app-password@gmail.com?to=ops@company.com` |
| **Outlook / M365** | `mailto://user:password@outlook.com?to=ops@company.com` |
| **Corporate relay (port 25, no auth)** | `mailto://relay.company.local:25?from=backups@company.com&to=ops@company.com&smtp=relay.company.local` |
| **SMTP with TLS (port 587)** | `mailtos://user:pass@smtp.company.com:587?from=backups@company.com&to=ops@company.com` |
| **Multiple recipients** | `mailto://user:pass@gmail.com?to=a@co.com,b@co.com&cc=mgr@co.com` |

### Other Services

| Service | URL Format |
|---------|-----------|
| Slack | `slack://TokenA/TokenB/TokenC/` |
| Discord | `discord://WebhookID/WebhookToken/` |
| Telegram | `tgram://BotToken/ChatID/` |
| Gotify | `gotify://hostname/token` |
| Ntfy | `ntfy://topic/` |
| Webhook (JSON) | `json://hostname/path` |

See the [Apprise wiki](https://github.com/caronc/apprise/wiki) for 100+ supported services.

---

## Backup Compression

Local and SMB destinations support optional gzip compression. Enable it in the destination form by checking the **Gzip backups** checkbox.

When enabled:
- Text config backups are saved as `.cfg.gz` instead of `.cfg`
- Reduces disk usage significantly for large configs
- The `latest` symlink updates to point to the compressed file

---

## Database Maintenance

A daily maintenance job runs automatically at **3:30 AM** (container local time):

| Task | Description |
|------|-------------|
| Retention sweep | Prunes old backup files per GFS policy |
| Stale cleanup | Marks `in_progress` backups older than 1 hour as failed |
| Job history purge | Deletes job run records older than 90 days |
| Record purge | Removes pruned backup DB rows older than 90 days |
| SQLite VACUUM | Reclaims disk space from deleted records |

Retention also runs after every backup job.

**Manual trigger:**
```bash
curl -u admin:password -X POST http://localhost:5005/api/v1/maintenance/run
```

---

## SSH Key Authentication

### Option A: Generate from Dashboard (recommended)

1. Go to **Credentials > Add** (or edit an existing credential)
2. Click **Generate SSH Key** — an RSA 4096-bit key pair is created
3. Copy the public key from the modal
4. Add the public key to your network devices' `authorized_keys`
5. Save the credential

Keys are stored in `ssh_keys/` with secure permissions (`600` for private, `644` for public).

### Option B: Provide Your Own Key

1. Generate an SSH key:
   ```bash
   ssh-keygen -t rsa -b 4096 -f ~/.ssh/vibenetbackup
   ```
2. Copy the public key to your devices:
   ```bash
   ssh-copy-id -i ~/.ssh/vibenetbackup.pub user@device-ip
   ```
3. Add a credential in VIBENetBackup with the SSH Key Path set to the private key path
4. For systemd installs, store the key where the service user can read it:
   ```bash
   sudo mkdir -p /opt/vibenetbackup/.ssh
   sudo cp ~/.ssh/vibenetbackup /opt/vibenetbackup/.ssh/
   sudo chown vibenetbackup:vibenetbackup /opt/vibenetbackup/.ssh/vibenetbackup
   sudo chmod 600 /opt/vibenetbackup/.ssh/vibenetbackup
   ```

---

## Authentication

- Login page at `/login` with username and password
- **Remember me for 14 days** — HMAC-SHA256 signed session cookie
- HTTP Basic Auth also supported for API / curl access
- Default credentials are auto-generated during install
- Change password: edit `AUTH_PASSWORD` in `.env` and restart, or use `./manage.sh set-password`

---

## HTTPS/SSL (recommended for production)

Use a reverse proxy like Nginx:

```nginx
server {
    listen 443 ssl http2;
    server_name backup.yourdomain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://localhost:5005;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

Or use Let's Encrypt with Certbot for free certificates.

---

## CORS (Cross-Origin Resource Sharing)

| Access method | CORS_ORIGINS value |
|---|---|
| Same machine | `http://localhost:5005` |
| LAN by IP | `http://192.168.1.50:5005` |
| Domain + reverse proxy | `https://backup.yourdomain.com` |
| Multiple origins | `http://localhost:5005,http://192.168.1.50:5005` |
| Allow all (development only) | `*` |

> **Docker note:** The pre-built Docker image defaults to `CORS_ORIGINS=*`. For production, restrict it to your actual IP or domain.

---

## System Hardening (systemd installs)

The systemd service created by `install.sh` runs with:
- Dedicated `vibenetbackup` user (no login shell)
- `NoNewPrivileges=true` — cannot gain privileges
- `ProtectSystem=strict` — read-only system files
- `ProtectHome=true` — cannot access user homes
- `PrivateTmp=true` — isolated /tmp
- `.env` and database: `600` permissions (owner-only)

---

## Network Security

- Restrict CORS origins to known IPs/domains
- Bind to localhost if using a reverse proxy: `HOST=127.0.0.1`
- Use firewall rules to restrict access:
  ```bash
  sudo ufw allow from 198.51.100.0/24 to any port 5005
  ```

---

## Troubleshooting

**Service fails to start:**
```bash
sudo journalctl -u vibenetbackup -f
```

**Permission denied on backups:**
```bash
sudo chown -R vibenetbackup:vibenetbackup /opt/vibenetbackup/backups
```

**Show or change admin password:**
```bash
cd /opt/vibenetbackup
./manage.sh show-password
./manage.sh set-password
./manage.sh reset-password
```

**Database locked:**
```bash
sudo lsof /opt/vibenetbackup/vibenetbackup.db
```

---

## Project Structure

```
vibenetbackup/
├── app/
│   ├── main.py              # FastAPI entry point
│   ├── config.py            # Settings management
│   ├── database.py          # SQLAlchemy setup
│   ├── models/              # Database models
│   ├── routers/             # API and web routes
│   ├── modules/             # Backup engines, scheduler, retention
│   ├── templates/           # Jinja2 HTML templates
│   └── static/              # CSS, JS, images
├── install.sh               # Production installer
├── uninstall.sh             # Uninstaller
├── manage.sh                # Password and service management
├── run.sh                   # Development runner
├── Dockerfile
├── docker/
│   ├── build-and-push.sh
│   ├── image/docker-compose.yml
│   └── build/docker-compose.yml
├── docs/                    # Documentation
├── requirements.txt
├── pyproject.toml
└── README.md
```
