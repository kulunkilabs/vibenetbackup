# VIBENetBackup

Network device configuration backup manager with multi-engine support, automated scheduling, and retention policies.

**Version:** 1.5 | **License:** MIT

<p align="center">
  <img src="docs/screenshots/v1.1/screensh_01.png" alt="VIBENetBackup Dashboard" width="900"/>
</p>

---

## Features

- **Multi-engine backup** — Netmiko (SSH), SCP, Oxidized REST API, pfSense/OPNsense API, Proxmox VE
- **Multi-destination storage** — Local, Git (GitHub/Gitea/Forgejo), SMB/CIFS
- **Automated scheduling** — Cron-based jobs with APScheduler
- **Retention management** — Grandfather-Father-Son (GFS) rotation
- **Change detection** — SHA256 hash comparison with unified diff viewer
- **Web UI** — Bootstrap 5 dark theme with HTMX live updates
- **REST API** — Full JSON API at `/api/v1/*`
- **Cookie-based auth** — 14-day sessions with HMAC-SHA256 signed tokens
- **Encrypted credentials** — Fernet encryption for stored passwords
- **Import from Oxidized** — Pull your device inventory in one click
- **Device groups** — Organize devices and credentials

---

## Quick Install

**One-liner (Linux with systemd):**
```bash
curl -fsSL https://raw.githubusercontent.com/kulunkilabs/vibenetbackup/main/install.sh | sudo bash
```

**Docker:**
```bash
mkdir vibenetbackup && cd vibenetbackup
curl -fsSL https://raw.githubusercontent.com/kulunkilabs/vibenetbackup/main/docker/image/docker-compose.yml -o docker-compose.yml
# Edit docker-compose.yml to set SECRET_KEY and AUTH_PASSWORD
docker compose up -d
```

**Access:** `http://<your-server-ip>:5005` — credentials shown during install.

> See [docs/INSTALL.md](docs/INSTALL.md) for all installation methods, Docker build-from-source, and upgrade instructions.

---

## Screenshots

<p align="center">
  <img src="docs/screenshots/v1.1/screensh_01.png" alt="Dashboard" width="800"/><br/>
  <em>Dashboard — device stats, recent backups, job status</em>
</p>

<p align="center">
  <img src="docs/screenshots/v1.1/screensh_02.png" alt="Devices" width="800"/><br/>
  <em>Devices — manage, test, backup with one click</em>
</p>

<p align="center">
  <img src="docs/screenshots/v1.1/screensh_03.png" alt="Backups" width="800"/><br/>
  <em>Backups — full history with hash, status, diff viewer</em>
</p>

<p align="center">
  <img src="docs/screenshots/v1.1/screensh_05.png" alt="Job History" width="800"/><br/>
  <em>Job History — scheduled backup run results</em>
</p>

---

## Supported Devices

| Vendor | Types |
|--------|-------|
| **Cisco** | IOS, IOS-XE, IOS-XR, NX-OS |
| **Nokia** | SR OS Classic CLI, SR OS MD-CLI (7750/7210/7450/7705) |
| **Brocade/Ruckus** | ICX / FastIron |
| **Arista** | EOS |
| **Juniper** | JunOS |
| **HP/Aruba** | ProCurve, Comware |
| **Dell** | OS6, OS9, OS10, Force10 |
| **pfSense/OPNsense** | API backup |
| **Proxmox VE** | SSH/SFTP (90+ config files as ZIP) |

> See [docs/DEVICES.md](docs/DEVICES.md) for setup guides, commands, and troubleshooting per vendor.

---

## Documentation

| Doc | Description |
|-----|-------------|
| [docs/INSTALL.md](docs/INSTALL.md) | All installation methods, Docker, upgrades, uninstall |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | Environment variables, secrets, CORS, security, HTTPS |
| [docs/DEVICES.md](docs/DEVICES.md) | Supported devices, Proxmox VE, Nokia SR OS, pfSense/OPNsense, Oxidized |
| [docs/API.md](docs/API.md) | REST API reference with curl examples |

---

## Support

If you find VIBENetBackup useful, consider buying me a coffee:

<a href="https://ko-fi.com/kulunkilabs" target="_blank">
  <img src="https://ko-fi.com/img/githubbutton_sm.svg" alt="Buy Me a Coffee at ko-fi.com" />
</a>

---

## Contributing

Contributions welcome! Fork the repo, create a feature branch, and submit a pull request.

## License

MIT License. See [LICENSE](LICENSE) for details.

---

## Links

- **Repository:** https://github.com/kulunkilabs/vibenetbackup
- **Issues:** https://github.com/kulunkilabs/vibenetbackup/issues
- **Releases:** https://github.com/kulunkilabs/vibenetbackup/releases

---

<p align="center">
  <sub>Built with FastAPI, SQLAlchemy, and Bootstrap</sub>
</p>
