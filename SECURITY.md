# Security Guide

## Security Features

### Authentication
All endpoints require authentication via cookie-based sessions (web UI) or HTTP Basic Auth (API).

**Default credentials:**
- Username: `admin`
- Password: auto-generated during install (or `changeme-strong-password` in Docker)

**Change credentials:** edit `AUTH_USERNAME` and `AUTH_PASSWORD` in `.env` (or `docker-compose.yml`) and restart.

### Credential Encryption
Device passwords and secrets are encrypted at rest using Fernet symmetric encryption, derived from your `SECRET_KEY`.

### Security Headers
The following headers are added to all responses:
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `X-XSS-Protection: 1; mode=block`
- `Strict-Transport-Security: max-age=31536000; includeSubDomains`
- `Content-Security-Policy`

### CORS
CORS is restricted to origins listed in `CORS_ORIGINS`. See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for details.

---

## Security Checklist

- [ ] Changed default `AUTH_PASSWORD` to a strong password
- [ ] Set a strong, random `SECRET_KEY` (32+ characters)
- [ ] Restricted `CORS_ORIGINS` to known IPs/domains only
- [ ] Enabled HTTPS via reverse proxy or direct SSL
- [ ] Configured firewall rules to restrict port 5005 access
- [ ] Regular backups of the database file
- [ ] Enabled automatic security updates on the server

---

## HTTPS/SSL (recommended for production)

### Option A: Reverse Proxy (recommended)

Use Nginx or similar as a reverse proxy with SSL termination:

```nginx
server {
    listen 443 ssl http2;
    server_name backup.yourdomain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    location / {
        proxy_pass http://localhost:5005;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Option B: Direct SSL with Uvicorn

```bash
# Generate self-signed certificate (testing only)
openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365 -nodes

# Run with SSL
uvicorn app.main:app --host 0.0.0.0 --port 5005 --ssl-keyfile key.pem --ssl-certfile cert.pem
```

---

## Network Hardening

### Bind to localhost
If using a reverse proxy, restrict the listen address:
```env
HOST=127.0.0.1
```

### Firewall rules
```bash
# Allow only specific subnets
sudo ufw allow from 198.51.100.0/24 to any port 5005

# Block external access if using reverse proxy
sudo ufw deny 5005/tcp
```

### Fail2ban
Block brute-force login attempts:

```bash
sudo apt install fail2ban
```

Create `/etc/fail2ban/filter.d/vibenetbackup.conf`:
```ini
[Definition]
failregex = ^.*INFO:.*<HOST>.*"POST /login HTTP.*" 401
```

Create or add to `/etc/fail2ban/jail.local`:
```ini
[vibenetbackup]
enabled = true
port = 5005
filter = vibenetbackup
logpath = /var/log/syslog
maxretry = 5
bantime = 3600
```

> **Note:** Adjust `logpath` to match your setup. For systemd installs, use `/var/log/syslog` or pipe journal output. For Docker, use `docker compose logs` output.

---

## Incident Response

If you suspect unauthorized access:

1. **Stop the application** — `sudo systemctl stop vibenetbackup` or `docker compose down`
2. **Check logs** — `sudo journalctl -u vibenetbackup` or `docker compose logs`
3. **Change all credentials** — update `AUTH_PASSWORD` in `.env`
4. **Regenerate SECRET_KEY** — this will invalidate all stored encrypted credentials (you will need to re-enter device passwords)
5. **Review database** — check for unauthorized changes
6. **Verify backups** — ensure backup files have not been tampered with

---

## Reporting Security Issues

If you discover a security vulnerability, please report it privately through GitHub:

- **GitHub Security Advisories:** [Report a vulnerability](https://github.com/kulunkilabs/vibenetbackup/security/advisories/new)

Please do not open public issues for security vulnerabilities.
