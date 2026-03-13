# VIBENetBackup Security Guide

## 🔐 Security Features Added

### 1. Authentication (HTTP Basic Auth)
All endpoints now require authentication using HTTP Basic Auth.

**Default credentials:**
- Username: `admin`
- Password: `changeme-strong-password` ⚠️ **CHANGE THIS!**

**To change credentials:**
```bash
# Edit the .env file
nano .env

# Change these values:
AUTH_USERNAME=your-username
AUTH_PASSWORD=your-strong-password
```

### 2. CORS Restrictions
CORS is now restricted to specific origins instead of allowing all (`*`).

**Configure allowed origins in `.env`:**
```bash
CORS_ORIGINS=http://localhost:5005,http://127.0.0.1:5005,http://0.0.0.0:5005
```

### 3. Security Headers
The following security headers are now added to all responses:
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `X-XSS-Protection: 1; mode=block`
- `Strict-Transport-Security: max-age=31536000; includeSubDomains`
- `Content-Security-Policy`

### 4. Rate Limiting
Rate limiting module is available (see below for setup).

### 5. File Permissions
Run `./secure_permissions.sh` to secure sensitive files.

---

## 🚀 Quick Security Setup

```bash
# 1. Set secure file permissions
chmod +x secure_permissions.sh
./secure_permissions.sh

# 2. Change default password in .env
nano .env
# Change: AUTH_PASSWORD=your-unique-strong-password

# 3. Restart the application
./run.sh
```

---

## 🔒 HTTPS/SSL Setup (Recommended for Production)

### Option A: Using a Reverse Proxy (Recommended)

Use Nginx or Apache as a reverse proxy with SSL:

**Nginx example:**
```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.com;
    
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
# Generate self-signed certificate (for testing)
openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365 -nodes

# Run with SSL
uvicorn app.main:app --host 0.0.0.0 --port 5005 --ssl-keyfile key.pem --ssl-certfile cert.pem
```

---

## 🛡️ Additional Security Recommendations

### 1. Network Binding
If you only access from localhost or via reverse proxy:

```bash
# In .env, change:
HOST=127.0.0.1  # Instead of 0.0.0.0
```

### 2. Firewall Rules

```bash
# Allow only specific IPs (example with ufw)
sudo ufw allow from 198.51.100.0/24 to any port 5005

# Or block external access completely if using reverse proxy
sudo ufw deny 5005/tcp
```

### 3. Fail2ban
Install fail2ban to block brute-force attempts:

```bash
sudo apt install fail2ban

# Create /etc/fail2ban/jail.local
[vibenetbackup]
enabled = true
port = 5005
filter = vibenetbackup
logpath = /var/log/vibenetbackup.log
maxretry = 5
bantime = 3600
```

### 4. Audit Logging
Enable audit logging by setting in `.env`:
```bash
LOG_LEVEL=INFO
```

---

## ⚠️ Security Checklist

- [ ] Changed default `AUTH_PASSWORD` from `changeme-strong-password`
- [ ] Set strong `SECRET_KEY` (32+ random characters)
- [ ] Restricted `CORS_ORIGINS` to known IPs/domains only
- [ ] Secured file permissions with `./secure_permissions.sh`
- [ ] Enabled HTTPS/SSL (via reverse proxy or direct)
- [ ] Configured firewall rules
- [ ] Disabled password login if using SSH keys for servers
- [ ] Regular backups of the database file
- [ ] Enabled automatic security updates on the server

---

## 🚨 Security Incident Response

If you suspect unauthorized access:

1. **Stop the application immediately**
2. **Check logs:** `tail -f /var/log/vibenetbackup.log` or check the log output
3. **Change all credentials:** Update `.env` with new passwords and keys
4. **Regenerate SECRET_KEY:** This will invalidate existing encrypted credentials
5. **Review database:** Check for unauthorized changes
6. **Check backups:** Verify backup integrity

---

## 📞 Reporting Security Issues

If you discover a security vulnerability, please report it responsibly.
