# VIBENetBackup

Network device configuration backup manager with support for multiple backup engines, storage destinations, automated scheduling, and retention policies.

**Version:** 1.1
**License:** MIT

---

## Features

- **Multi-engine backup** — Netmiko (SSH), SCP (Paramiko), Oxidized REST API, pfSense/OPNsense API, Proxmox VE (SSH/SFTP)
- **Multi-destination storage** — Local filesystem, Git (GitHub/Gitea/Forgejo with token, SSH, or username/password), SMB/CIFS shares
- **Proxmox VE backup** — Collects 90+ config files via SFTP, stores as ZIP, file browser with per-file download and inline viewer
- **Import from Oxidized** — Pull your entire device inventory in one click
- **Groups** — Organise devices and credentials into named groups
- **Automated scheduling** — Cron-based with APScheduler
- **Retention management** — Grandfather-Father-Son (GFS) rotation
- **Change detection** — SHA256 hash comparison, unified diff viewer
- **Web UI** — Bootstrap 5 dark theme with HTMX
- **REST API** — Full JSON API at `/api/v1/*`
- **Cookie-based authentication** — 14-day remember-me sessions (HMAC-SHA256 signed tokens)
- **Encrypted credentials** — Fernet encryption for stored passwords
- **Security hardened** — Systemd service with NoNewPrivileges, dedicated user

---

## Installation
### Method 1: Quick Install (Recommended for Production)

One-command installation with systemd service:

```bash
curl -fsSL https://raw.githubusercontent.com/kulunkilabs/vibenetbackup/main/install.sh | sudo bash
```

**What it does:**
- Installs Python 3.11+, git, and dependencies
- Creates dedicated `vibenetbackup` system user
- Clones repo to `/opt/vibenetbackup`
- Sets up Python virtual environment
- Generates secure `.env` with random admin password
- Creates systemd service with security hardening
- Starts the service on port 5005

**Access the web UI:**
```
http://<your-server-ip>:5005
Username: admin
Password: (shown during installation)
```

**Service management:**
```bash
sudo systemctl {start|stop|restart|status} vibenetbackup
sudo journalctl -u vibenetbackup -f  # View logs
```

**Management commands:**
```bash
cd /opt/vibenetbackup
./manage.sh show-password     # Show current password
./manage.sh set-password      # Change password
./manage.sh reset-password    # Generate new random password
./manage.sh status            # Show service status
./manage.sh logs              # View logs
```

**To update:**
```bash
curl -fsSL https://raw.githubusercontent.com/kulunkilabs/vibenetbackup/main/install.sh | sudo bash
```

---

### Method 2: Git Clone + run.sh (Development/Customization)

For development, customization, or running without systemd:

```bash
git clone https://github.com/kulunkilabs/vibenetbackup.git
cd vibenetbackup
./run.sh
```

**What it does:**
- Creates Python virtual environment (`.venv`)
- Installs dependencies from `requirements.txt`
- Creates `.env` from `.env.example` if missing
- Starts server on http://localhost:5005

**For production with this method:**
```bash
cp .env.example .env
# Edit .env to set AUTH_PASSWORD, SECRET_KEY, etc.
nano .env
./run.sh
```

---

### Method 3: Docker — Pre-built Image (Recommended)

Use the pre-built image from GitHub Container Registry — no need to clone the repo or build anything.

**1. Download the compose file:**
```bash
mkdir vibenetbackup && cd vibenetbackup
curl -fsSL https://raw.githubusercontent.com/kulunkilabs/vibenetbackup/main/docker/image/docker-compose.yml -o docker-compose.yml
```

**2. Edit the environment variables directly in `docker-compose.yml`:**
```bash
nano docker-compose.yml
```

Change at minimum `SECRET_KEY` and `AUTH_PASSWORD`:
```yaml
    environment:
      - SECRET_KEY=change-me-to-a-random-secret-key
      - AUTH_PASSWORD=changeme-strong-password
      - CORS_ORIGINS=*
```

> **CORS note:** `CORS_ORIGINS=*` allows access from any origin — convenient for getting started. For production, restrict it to your actual IP or domain:
> ```
> CORS_ORIGINS=http://192.168.1.50:5005,https://backup.yourdomain.com
> ```
> Use the address users type in their browser, not the Docker internal network IP.

Generate a secure `SECRET_KEY`:
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

**3. Start:**
```bash
docker compose up -d
```

**Access:** http://localhost:5005

**To update:**
```bash
docker compose pull
docker compose up -d
```

---

### Building and Publishing the Image (maintainers)

To build a new image and push it to the container registry so others can use Method 3:

```bash
# From the repo root — builds, tags :1.1 + :latest, and pushes
bash docker/build-and-push.sh 1.1
```

The script will prompt for your registry credentials on first run. After it completes, `docker compose pull` in any Method 3 deployment will pick up the new image.

---

### Method 4: Docker — Build from Source

For development or customization, build the image yourself:

```bash
git clone https://github.com/kulunkilabs/vibenetbackup.git
cd vibenetbackup
cp .env.example .env
# Edit .env to set AUTH_PASSWORD, SECRET_KEY, etc.
nano .env
cd docker/build
docker compose up -d --build
```

**To update:**
```bash
cd vibenetbackup
git pull
cd docker/build
docker compose up -d --build
```

### Upgrading Docker Engine

If you have an old version of Docker installed (e.g. `docker-compose` v1 or `docker.io` from distro repos), upgrade to the official Docker Engine:

```bash
# Remove old Docker packages
sudo apt remove docker docker-engine docker.io containerd runc

# Add Docker's official GPG key and repository
sudo apt update
sudo apt install ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install latest Docker Engine with Compose plugin
sudo apt update
sudo apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Verify installation
docker --version
docker compose version
```

> **Note:** The new Docker uses `docker compose` (with a space) instead of the old `docker-compose` (with a hyphen).

---

## Configuration

All settings are stored in `.env`:

```env
# Database
DATABASE_URL=sqlite:///./vibenetbackup.db

# Security (change these!)
SECRET_KEY=<any-strong-secret-string>
AUTH_USERNAME=admin
AUTH_PASSWORD=<auto-generated-password>

# Network
HOST=0.0.0.0
PORT=5005

# CORS - comma-separated allowed origins
CORS_ORIGINS=http://localhost:5005,http://127.0.0.1:5005,http://0.0.0.0:5005

# Paths
BACKUP_DIR=./backups

# Integrations (use localhost if Oxidized is on the same host, otherwise use its IP)
OXIDIZED_URL=http://localhost:8888

# Logging
LOG_LEVEL=INFO
```

**Important:** Change `AUTH_PASSWORD` and `SECRET_KEY` for production!

### SECRET_KEY

The `SECRET_KEY` is used to encrypt credential passwords and enable secrets stored in the database using Fernet symmetric encryption. Any string can be used — it is automatically derived into a valid encryption key via SHA-256.

**Requirements:**
- Can be any string (no format restrictions)
- Should be long and random for production use
- Must remain the same across restarts — changing it will make existing encrypted credentials unreadable

**Generate a secure key:**
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Or with OpenSSL:
```bash
openssl rand -base64 32
```

The `install.sh` and `run.sh` scripts auto-generate a random `SECRET_KEY` if one is not already set in `.env`.

> **Warning:** If you change `SECRET_KEY` after credentials have been saved, all stored passwords and enable secrets will become undecryptable. You will need to re-enter them.

---

## First Steps

1. **Login** — Use credentials from installation (or `admin`/`changeme-strong-password` for dev)
2. **Credentials** — Add SSH credentials for your devices ( username + password or SSH key )
3. **Devices** — Add devices manually or [**Import from Oxidized**](#oxidized-integration)
4. **Test** — Click **Test All** to verify SSH connectivity
5. **Destinations** — Configure where backups are stored (local, git, SMB)
6. **Schedule** — Set up automated backups with cron expressions
7. **Retention** — Configure GFS retention policies

---

## SSH Key Authentication

VIBENetBackup supports SSH key-based authentication as an alternative to password authentication.

### Option A: Generate from Dashboard (Recommended)

1. **Go to Credentials → Add** (or edit an existing credential)
2. **Click "Generate SSH Key"** next to the SSH Key Path field
3. An RSA 4096-bit key pair is created on the server and the path is auto-filled
4. **Copy the public key** from the modal that appears
5. **Add the public key** to your network devices' `authorized_keys`
6. **Save** the credential

Keys are stored in the `ssh_keys/` directory with secure permissions (`600` for private, `644` for public).

### Option B: Provide Your Own Key

1. **Generate an SSH key** on the server or your workstation:
   ```bash
   ssh-keygen -t rsa -b 4096 -f ~/.ssh/vibenetbackup
   ```
2. **Copy the public key** to your network devices:
   ```bash
   ssh-copy-id -i ~/.ssh/vibenetbackup.pub user@device-ip
   ```
3. **Add a credential** in VIBENetBackup:
   - **Username:** your SSH username
   - **Password:** leave empty (or set the key passphrase if applicable)
   - **SSH Key Path:** full path to the private key (e.g. `/home/user/.ssh/vibenetbackup`)
4. **Assign the credential** to your devices

### Notes

- The application stores the **file path** to the private key, not the key contents
- The key file must be readable by the user running VIBENetBackup (e.g. `vibenetbackup` for systemd installs)
- Dashboard-generated keys are saved to `ssh_keys/` which is already accessible to the service user
- For manually provided keys on systemd installs, store them in an accessible location:
  ```bash
  sudo mkdir -p /opt/vibenetbackup/.ssh
  sudo cp ~/.ssh/vibenetbackup /opt/vibenetbackup/.ssh/
  sudo chown vibenetbackup:vibenetbackup /opt/vibenetbackup/.ssh/vibenetbackup
  sudo chmod 600 /opt/vibenetbackup/.ssh/vibenetbackup
  ```
- Key files are **not deleted** when a credential is removed (for safety)
- Both Netmiko (SSH) and SCP backup engines support key-based authentication

---

## Oxidized Integration

VIBENetBackup can import your existing device inventory from [Oxidized](https://github.com/ytti/oxidized) and use it as a backup source.

### Default Ports

| Tool | Default Port | Configuration |
|------|--------------|---------------|
| **VIBENetBackup** | `5005` | `PORT=5005` in `.env` |
| **Oxidized** | `8888` | `OXIDIZED_URL=http://<oxidized-ip>:8888` in `.env` (see [binding note](#oxidized-rest-api-binding)) |

### Oxidized REST API Binding

By default, Oxidized binds its REST API to `127.0.0.1`, which means it only accepts connections from localhost. If VIBENetBackup runs on a **different host** than Oxidized, you must configure Oxidized to bind to `0.0.0.0`:

In your Oxidized config (`~/.config/oxidized/config` or `/etc/oxidized/config`):

```yaml
rest: 0.0.0.0:8888
```

Then update the Oxidized URL in VIBENetBackup `.env` to point to the Oxidized host IP:

```env
OXIDIZED_URL=http://192.0.2.10:8888
```

If both services run on the **same host**, the default `127.0.0.1` binding works fine and no changes are needed.

### Import Devices from Oxidized

1. **Ensure Oxidized is running** on its default port (8888)
2. **Configure the Oxidized URL** in VIBENetBackup `.env`:
   ```env
   # Use localhost if on the same host, otherwise use the Oxidized server IP
   OXIDIZED_URL=http://localhost:8888
   OXIDIZED_URL=http://192.0.2.10:8888
   ```
3. **Go to Devices → Import from Oxidized**
4. Click **Import** to pull all devices from Oxidized

### Using Oxidized as Backup Engine

VIBENetBackup can also fetch configurations via Oxidized's REST API:

1. **Add credentials** for your devices (same as Oxidized uses)
2. **Create a device** with device type set to use Oxidized engine
3. **Run backup** — VIBENetBackup will query Oxidized for the latest config

This is useful when:
- You want to migrate from Oxidized gradually
- Oxidized has better support for certain device types
- You want to use Oxidized's collection but VIBENetBackup's storage/retention

---

## pfSense / OPNsense Integration

VIBENetBackup supports backing up pfSense and OPNsense firewalls via their web APIs. Both are FreeBSD-based and use the `pfsense` backup engine.

### OPNsense Setup

OPNsense uses **API key/secret** pairs — regular web UI credentials will not work.

1. **Create an API key** in OPNsense:
   - Log into the OPNsense web UI
   - Go to **System > Access > Users**
   - Edit the backup user (or create a dedicated one)
   - Scroll to **API keys**, click **+** to generate a new key pair
   - Save the downloaded `apikey.txt` — it contains the key and secret
2. **Assign the required privilege:**
   - Edit the user (or its group) and add the **Diagnostics: Configuration History** privilege
   - This grants access to the `/api/core/backup/` endpoints
3. **Add credential** in VIBENetBackup:
   - **Username:** the API key (e.g. `w86XNZob/8Oq8aC5r0kbNarNtdpo...`)
   - **Password:** the API secret (e.g. `XeD26XVrJ5ilAc/EmglCRC+0j2e5...`)
4. **Add device:**
   - **Device type:** OPNsense Firewall (FreeBSD)
   - **Backup engine:** pfSense/OPNsense (API)
   - **Port:** 443 (or your custom web UI port)
   - Assign the credential from step 3

### pfSense Setup

pfSense supports two API methods. The engine tries both automatically:

**Option A — pfSense REST API package (recommended):**
1. Install the [pfSense REST API](https://pfrest.org/) package on your firewall
2. Create an API user or use an existing admin account
3. **Add credential** in VIBENetBackup with the API username and password
4. The engine will use `/api/v1/config/backup`

**Option B — PHP endpoint (no package needed):**
1. **Add credential** with your pfSense web UI username and password
2. **Required privilege:** The user must have the **WebCfg - Diagnostics: Backup & Restore** privilege
   - Go to **System > User Manager > Edit User > Effective Privileges**
   - Add `WebCfg - Diagnostics: Backup & Restore` (or use an admin account)
3. The engine will use `/diag_backup.php` with CSRF token handling

**Add device:**
- **Device type:** pfSense Firewall (FreeBSD)
- **Backup engine:** pfSense/OPNsense (API)
- **Port:** 443 (or your custom web UI port)
- Assign the credential

### Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| **401 — Authentication failed** (OPNsense) | Using web UI credentials instead of API key/secret | Create API key in System > Access > Users > API keys |
| **401 — Authentication failed** (pfSense) | Wrong username or password | Verify web UI credentials or REST API credentials |
| **403 — Access denied** (OPNsense) | API key works but user lacks privilege | Add **Diagnostics: Configuration History** to the user (System > Access > Users > Effective Privileges) |
| **403 — Access denied** (pfSense) | User lacks backup privilege | Add **WebCfg - Diagnostics: Backup & Restore** to the user (System > User Manager > Effective Privileges) |
| **Connection timeout** | Wrong IP, port, or firewall blocking access | Verify the IP and web UI port, check firewall rules |
| **SSL error then HTTP fallback** | Normal — HTTPS tried first, falls back to HTTP | No action needed (or configure HTTPS on the firewall) |

### Notes

- **HTTPS/HTTP:** The engine tries HTTPS first and falls back to HTTP automatically
- **Self-signed certificates:** Accepted by default (common on firewall web UIs)
- **SSH fallback:** If you set the backup engine to Netmiko (SSH) instead, it will use `cat /cf/conf/config.xml` (pfSense) or `cat /conf/config.xml` (OPNsense) over SSH
- **Custom ports:** Set the port field to match your firewall's web UI port (e.g. 8443)

---

## Supported Devices

| Vendor | Netmiko Type | Config Command |
|--------|--------------|----------------|
| Brocade/Ruckus ICX | `ruckus_fastiron` | `show running-config` |
| Nokia SR OS Classic CLI (7750/7210/7450/7705) | `nokia_sros` | `admin display-config` |
| Nokia SR OS MD-CLI (7750/7210/7450/7705) | `nokia_sros_md` | `admin show configuration` |
| Cisco IOS/XE/XR/NX-OS | `cisco_ios` / `cisco_xe` / `cisco_xr` / `cisco_nxos` | `show running-config` |
| HP ProCurve / Aruba | `hp_procurve` | `show running-config` |
| HP Comware | `hp_comware` | `display current-configuration` |
| Dell OS6/OS9/OS10 | `dell_os6` / `dell_os9` / `dell_os10` | `show running-config` |
| Dell Force10 | `dell_force10` | `show running-config` |
| QuantaMesh | `quanta_mesh` | `show running-config` |
| Arista EOS | `arista_eos` | `show running-config` |
| Juniper JunOS | `juniper_junos` | `show configuration \| display set` |
| pfSense | `pfsense` | API or `cat /cf/conf/config.xml` |
| OPNsense | `opnsense` | API or `cat /conf/config.xml` |
| Proxmox VE | `proxmox` | SFTP — /etc/pve, /etc/network, /root/.ssh, and 80+ paths |

Adding a new device type is one line in `app/models/device.py` — no migration needed.

---

## Proxmox VE Integration

VIBENetBackup collects Proxmox VE configuration files over SSH/SFTP and stores them as a ZIP archive — no Proxmox API token needed.

### What is collected

The backup engine collects 90+ paths including:

| Path | Contents |
|------|----------|
| `/etc/pve/` | All Proxmox cluster/node config (VMs, storage, users, firewall) |
| `/etc/network/interfaces` | Network interface configuration |
| `/root/.ssh/` | SSH authorized keys and known hosts |
| `/etc/cron*` | Cron jobs |
| `/etc/hostname`, `/etc/hosts` | Host identity |
| `/etc/fstab` | Filesystem mounts |
| `/var/lib/pve-cluster/config.db` | Cluster database |

### Setup

1. **Add a credential** in VIBENetBackup:
   - **Username:** `root` (or a user with SSH access and read access to `/etc/pve`)
   - **Password:** SSH password, or use an SSH key
2. **Add a device:**
   - **Device type:** `Linux Server` (or any)
   - **Backup engine:** `Proxmox VE (SSH/SFTP)`
   - **IP address:** Proxmox host IP or hostname
   - **Port:** 22 (default SSH)
3. **Run backup** — files are collected over SFTP, zipped on the server, and saved to the backup directory

### Backup result in the dashboard

- The **Backups** list shows the backup with a ZIP icon
- Click the backup to open the **file browser** — all collected files are listed
- Click the **eye icon** to view a file inline in a modal
- Click the **download icon** to download a single file
- Click **Download ZIP** to download the full archive
- Click **Delete** to remove the backup record and file from disk

### Notes

- Missing paths are silently skipped (normal — not all systems have all files)
- Change detection works via SHA256 hash of the full ZIP — unchanged backups are skipped
- The ZIP is stored in the backup directory under `<hostname>/`; a JSON manifest is stored in the database

---

## Nokia SR OS Notes

Nokia SR OS devices (7750, 7210, 7450, 7705 SAR) require extra connection timing due to their prompt format. VIBENetBackup automatically applies `global_delay_factor=2` and extended timeouts for all Nokia SR OS device types.

### Classic CLI vs MD-CLI

| CLI Mode | Device Type | Config Command | Prompt Format |
|----------|-------------|----------------|---------------|
| Classic (pre-16.0) | `nokia_sros` | `admin display-config` | `*A:hostname#` |
| MD-CLI (16.0+) | `nokia_sros_md` | `admin show configuration` | `[/]A:admin@hostname#` |

**How to check which CLI mode your device uses:**
```
# Classic CLI prompt looks like:
*A:sar7705-rr51#

# MD-CLI prompt looks like:
[/]
A:admin@sar7705-rr51#
```

Choose `nokia_sros` for classic CLI or `nokia_sros_md` for MD-CLI accordingly.

### Troubleshooting Nokia Devices

| Error | Cause | Fix |
|-------|-------|-----|
| **Pattern not detected** | Netmiko can't match the device prompt | Verify you selected the correct CLI mode (classic vs MD-CLI). Connection test may still show success if SSH auth passed. |
| **Timeout after authentication** | Device is slow to present prompt | Handled automatically — `global_delay_factor=2` is applied for Nokia devices |
| **Wrong config output** | Classic CLI command sent to MD-CLI device (or vice versa) | Change device type: `nokia_sros` for classic, `nokia_sros_md` for MD-CLI |

---

## API Examples

### Authentication
All API requests require HTTP Basic Auth:

```bash
# Set credentials
AUTH="admin:your-password"

# List devices
curl -u "$AUTH" http://localhost:5005/api/v1/devices

# Create device
curl -u "$AUTH" -X POST http://localhost:5005/api/v1/devices \
  -H "Content-Type: application/json" \
  -d '{
    "hostname": "switch01",
    "ip_address": "192.0.2.1",
    "device_type": "cisco_ios",
    "credential_id": 1
  }'

# Trigger backup
curl -u "$AUTH" -X POST http://localhost:5005/api/v1/backups/trigger \
  -H "Content-Type: application/json" \
  -d '{"device_ids": [1]}'

# List backups
curl -u "$AUTH" http://localhost:5005/api/v1/backups

# Run retention sweep
curl -u "$AUTH" -X POST http://localhost:5005/api/v1/retention/sweep
```

---

## Security

### Authentication
- Login page at `/login` with username and password
- **Remember me for 14 days** — HMAC-SHA256 signed session cookie, no re-login needed
- HTTP Basic Auth still supported for API / curl access
- Default credentials auto-generated during install (shown at the end of `install.sh`)
- Change password in `.env`: `AUTH_PASSWORD=your-strong-password`, then restart the service

### HTTPS/SSL (Recommended for Production)
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

Or use Let's Encrypt with Certbot.

### System Hardening (install.sh method)
The systemd service runs with:
- Dedicated `vibenetbackup` user (no login shell)
- `NoNewPrivileges=true` — cannot gain privileges
- `ProtectSystem=strict` — read-only system files
- `ProtectHome=true` — cannot access user homes
- `PrivateTmp=true` — isolated /tmp
- `.env` and database files: `600` permissions

### CORS (Cross-Origin Resource Sharing)

CORS controls which browser origins can access your VIBENetBackup instance. Set `CORS_ORIGINS` based on how users access the web UI:

| Access method | CORS_ORIGINS value |
|---|---|
| Same machine | `http://localhost:5005` |
| LAN by IP | `http://192.168.1.50:5005` (your host IP) |
| Domain + reverse proxy | `https://backup.yourdomain.com` |
| Multiple origins | `http://localhost:5005,http://192.168.1.50:5005` |
| Allow all (development only) | `*` |

> **Docker note:** The Docker pre-built image (`docker/image/docker-compose.yml`) defaults to `CORS_ORIGINS=*` for convenience. For production, change it to your actual IP or domain to restrict access.

### Network Security
- Restrict CORS origins in `.env` or `docker-compose.yml` (comma-separated)
- Bind to localhost only if using reverse proxy: `HOST=127.0.0.1`
- Use firewall rules to restrict access:
  ```bash
  sudo ufw allow from 198.51.100.0/24 to any port 5005
  ```

---

## Uninstallation

### Quick Uninstall

```bash
curl -fsSL https://raw.githubusercontent.com/kulunkilabs/vibenetbackup/main/uninstall.sh | sudo bash
```

**Options:**
- Keeps backup data and database by default
- Asks before removing service user
- Use `--remove-data` equivalent by answering 'n' to keep data prompt

### Manual Uninstall

```bash
# Stop service
sudo systemctl stop vibenetbackup
sudo systemctl disable vibenetbackup

# Remove files
sudo rm -f /etc/systemd/system/vibenetbackup.service
sudo rm -rf /opt/vibenetbackup

# Remove user (optional)
sudo userdel vibenetbackup

# Reload systemd
sudo systemctl daemon-reload
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

# Show current password
./manage.sh show-password

# Change password interactively
./manage.sh set-password

# Generate new random password
./manage.sh reset-password

# Show service status
./manage.sh status

# View logs
./manage.sh logs
```

Or manually edit `.env`:
```bash
sudo nano /opt/vibenetbackup/.env
sudo systemctl restart vibenetbackup
```

**Database locked:**
```bash
# Check for zombie processes
sudo lsof /opt/vibenetbackup/vibenetbackup.db
sudo kill -9 <pid>
```

---

## Project Structure

```
vibenetbackup/
├── app/
│   ├── main.py              # FastAPI entry point
│   ├── config.py            # Settings management
│   ├── database.py          # SQLAlchemy setup
│   ├── version.py           # Version info
│   ├── models/              # Database models
│   ├── routers/             # API routes
│   ├── modules/             # Backup engines, scheduler
│   ├── templates/           # Jinja2 templates
│   └── static/              # CSS, JS, images
├── install.sh               # Production installer
├── uninstall.sh             # Uninstaller
├── manage.sh                # Password & service management
├── run.sh                   # Development runner
├── Dockerfile
├── docker/
│   ├── build-and-push.sh       # Build image & push to container registry
│   ├── image/
│   │   └── docker-compose.yml  # Pre-built image (inline env)
│   └── build/
│       └── docker-compose.yml  # Build from source (uses .env)
├── requirements.txt
├── pyproject.toml
├── README.md
└── LICENSE
```

---

## Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

---

## License

MIT License. See [LICENSE](LICENSE) for details.

---

## Screenshots

<p align="center">
  <img src="docs/screenshots/demo_03-03-2026.png" alt="VIBENetBackup Dashboard" width="900"/>
  <br/>
  <em>VIBENetBackup Web Interface - Dashboard with backup statistics, device overview, and quick actions</em>
</p>


## Support

If you find VIBENetBackup useful, consider buying me a coffee:

<a href="https://ko-fi.com/kulunkilabs" target="_blank">
  <img src="https://ko-fi.com/img/githubbutton_sm.svg" alt="Buy Me a Coffee at ko-fi.com" />
</a>

---

## Links

- **Repository:** https://github.com/kulunkilabs/vibenetbackup
- **Issues:** https://github.com/kulunkilabs/vibenetbackup/issues
- **Releases:** https://github.com/kulunkilabs/vibenetbackup/releases

---

<p align="center">
  <sub>Built with FastAPI, SQLAlchemy, and Bootstrap</sub>
</p>
