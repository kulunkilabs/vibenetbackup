# Supported Devices

## Device Types & Config Commands

| Vendor | Netmiko Type | Config Command |
|--------|--------------|----------------|
| Brocade/Ruckus ICX | `ruckus_fastiron` | `show running-config` |
| Nokia SR OS Classic CLI (7750/7210/7250 IXR/7450/7705) | `nokia_sros` | `admin display-config` |
| Nokia SR OS MD-CLI (7750/7210/7250 IXR/7450/7705) | `nokia_sros_md` | `admin show configuration` |
| Cisco IOS/XE/XR/NX-OS | `cisco_ios` / `cisco_xe` / `cisco_xr` / `cisco_nxos` | `show running-config` |
| HP ProCurve / Aruba | `hp_procurve` | `show running-config` |
| HP Comware | `hp_comware` | `display current-configuration` |
| Dell OS6/OS9/OS10 | `dell_os6` / `dell_os9` / `dell_os10` | `show running-config` |
| Dell Force10 | `dell_force10` | `show running-config` |
| QuantaMesh | `quanta_mesh` | `show running-config` |
| Arista EOS | `arista_eos` | `show running-config` |
| Juniper JunOS | `juniper_junos` | `show configuration \| display set` |
| MikroTik RouterOS | `mikrotik_routeros` | `/export` |
| pfSense | `pfsense` | API or `cat /cf/conf/config.xml` via SSH |
| OPNsense | `opnsense` | API or `cat /conf/config.xml` via SSH |
| Proxmox VE | `proxmox` | SFTP — /etc/pve, /etc/network, and 80+ paths |

Adding a new device type is one line in `app/models/device.py` — no migration needed.

---

## Backup Engines

| Engine | How it works |
|--------|-------------|
| **Netmiko (SSH)** | Connects via SSH, runs config command, captures output |
| **SCP (Paramiko)** | Downloads config file via SCP/SFTP |
| **Oxidized REST API** | Fetches latest config from Oxidized's REST endpoint |
| **pfSense/OPNsense API** | Downloads config via firewall web API |
| **Proxmox VE (SSH/SFTP)** | Collects 90+ config files via SFTP, stores as tar.gz |

---

## SSH Proxy / Jump Host

VIBENetBackup supports backing up devices that are not directly reachable from the server — for example, routers and switches at remote sites that sit behind a NAT or firewall. This works by routing SSH connections through an intermediate jump host (also called a bastion host or proxy host).

### How It Works

Without a jump host, VIBENetBackup connects directly:

```
VIBENetBackup ──SSH──► Device
```

With a jump host, VIBENetBackup SSHes to the jump host first, then opens a channel from there to the target device:

```
VIBENetBackup ──SSH──► Jump Host ──SSH channel──► Device
```

This is the same two-hop approach used by Oxidized's SSH proxy feature and OpenSSH's `ProxyJump` directive. VIBENetBackup implements it using Paramiko's `direct-tcpip` channel, which is transparent to the target device.

### Typical Setup: autossh Remote Sites

A common deployment pattern is to have remote sites maintain a persistent reverse SSH tunnel to a central jump host using autossh. Each remote device gets a unique port on the jump host:

```
Remote site A — router ──autossh──► jump-host:2201
Remote site B — switch ──autossh──► jump-host:2202
Remote site C — router ──autossh──► jump-host:2203
```

VIBENetBackup then backs up through the jump host:

```
VIBENetBackup ──SSH──► jump-host:22 ──channel──► jump-host:2201 ──► site-A router
```

### Device Configuration

In the device **Add / Edit** form, scroll to the **SSH Proxy / Jump Host** section (visible for Netmiko and SCP engines):

| Field | Description |
|-------|-------------|
| **Proxy Host** | IP address or hostname of the jump host |
| **Proxy Port** | SSH port on the jump host (default: 22) |
| **Proxy Credential** | Credential to authenticate to the jump host — leave as *Same as device* if the jump host uses the same username/password as the target device |

**Example — autossh setup:**

| Field | Value |
|-------|-------|
| IP Address | `192.168.1.1` (device LAN IP) |
| Port | `22` (device SSH port) |
| Proxy Host | `203.0.113.10` (jump host public IP) |
| Proxy Port | `22` (jump host SSH port) |
| Proxy Credential | *Same as device* or a dedicated jump host credential |

### Device List Indicator

Devices configured with a jump host show a `⬡` icon next to their IP address in the device list. Hovering the icon shows the jump host address and, if a separate proxy credential is configured, the proxy username.

### Supported Engines

| Engine | Jump Host Support |
|--------|------------------|
| **Netmiko (SSH)** | Yes |
| **SCP (Paramiko)** | Yes |
| **Oxidized REST API** | Handled by Oxidized (see below) |
| **pfSense/OPNsense API** | No (HTTPS, not SSH) |
| **Proxmox VE** | Planned |

### Proxy Credentials

If the jump host requires different credentials than the target device, create a separate credential entry (e.g. `jump-host-creds`) and select it in the **Proxy Credential** dropdown. The engine will use the proxy credential for the jump host SSH connection and the device credential for the device SSH connection.

If left as *Same as device*, the device credential is used for both hops.

---

## Oxidized Integration

VIBENetBackup can import your device inventory from [Oxidized](https://github.com/ytti/oxidized) and use it as a backup source.

### Default Ports

| Tool | Default Port | Configuration |
|------|--------------|---------------|
| **VIBENetBackup** | `5005` | `PORT=5005` in `.env` |
| **Oxidized** | `8888` | `OXIDIZED_URL=http://<oxidized-ip>:8888` in `.env` |

### Oxidized REST API Binding

By default, Oxidized binds its REST API to `127.0.0.1`. If VIBENetBackup runs on a **different host**, configure Oxidized to bind to `0.0.0.0`:

```yaml
# ~/.config/oxidized/config
rest: 0.0.0.0:8888
```

Then set the URL in VIBENetBackup:
```env
OXIDIZED_URL=http://192.0.2.10:8888
```

### Import Devices

1. Ensure Oxidized is running
2. Configure `OXIDIZED_URL` in `.env`
3. Go to **Devices > Import from Oxidized**
4. Click **Import**

### Using Oxidized as Backup Engine

VIBENetBackup can fetch configs via Oxidized's REST API. Useful when:
- Migrating from Oxidized gradually
- Oxidized has better support for certain device types
- You want Oxidized's collection with VIBENetBackup's storage/retention
- Oxidized is already handling SSH proxy/jump-host connections to remote devices

VIBENetBackup fetches configs by **device hostname** (node name in Oxidized), not IP address. This is required for jump-host setups where multiple devices share the same jump-host IP — Oxidized identifies nodes by name, not IP.

### Oxidized + Jump Host

If your Oxidized instance is already configured to reach devices through a jump host (via `ProxyCommand`, `ProxyJump`, or Oxidized's `ssh_proxy` setting), VIBENetBackup works transparently — it just calls Oxidized's REST API and receives the config. No jump-host configuration needed in VIBENetBackup for the Oxidized engine.

When importing from Oxidized in a jump-host setup, the import table shows the port from each Oxidized node — non-22 ports (autossh forwarded ports) are highlighted in yellow.

---

## pfSense / OPNsense Integration

Both are supported via their web APIs using the `pfsense` backup engine.

### OPNsense Setup

OPNsense uses **API key/secret** pairs — regular web UI credentials will not work.

1. **Create an API key** in OPNsense:
   - Go to **System > Access > Users**
   - Edit the backup user > **API keys** > click **+**
   - Save the downloaded `apikey.txt`
2. **Add privilege:** **Diagnostics: Configuration History**
3. **Add credential** in VIBENetBackup:
   - **Username:** the API key (from `apikey.txt`)
   - **Password:** the API secret (from `apikey.txt`)
4. **Add device:**
   - **Type:** OPNsense Firewall (FreeBSD)
   - **Engine:** pfSense/OPNsense (API)
   - **Port:** 443 (or your web UI port)

### pfSense Setup

The engine tries two methods automatically and uses whichever works:

**Option A — pfSense REST API package:**
1. Install the [pfSense REST API](https://pfrest.org/) package from **System > Package Manager**
2. Add credential in VIBENetBackup with your API username and password

**Option B — Web UI login (no package needed):**
1. Add credential in VIBENetBackup with your **web UI username and password**
2. The user must have the **WebCfg - Diagnostics: Backup & Restore** privilege
3. Works with pfSense CE 2.7+ and pfSense Plus 24.x+

The engine handles the full login flow automatically: CSRF token, session authentication, and config download.

**Add device:** Type: pfSense Firewall, Engine: pfSense/OPNsense (API), Port: 443

### pfSense / OPNsense Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| **401** (OPNsense) | Using web UI credentials instead of API key | Create API key in System > Access > Users |
| **401** (pfSense) | Wrong credentials | Verify web UI or REST API credentials |
| **403** (OPNsense) | Missing privilege | Add **Diagnostics: Configuration History** |
| **403** (pfSense) | Missing privilege | Add **WebCfg - Diagnostics: Backup & Restore** |
| **CSRF validation failed** | CSRF token issue | Ensure pfSense is reachable and credentials are correct |
| **Connection timeout** | Wrong IP or port | Verify IP and web UI port (default 443) |
| **SSL error then HTTP** | Normal behavior | HTTPS is tried first, falls back to HTTP automatically |

### pfSense / OPNsense Notes

- HTTPS tried first, falls back to HTTP automatically
- Self-signed certificates accepted by default
- SSH fallback: set engine to **Netmiko** to use `cat /cf/conf/config.xml` over SSH
- Custom ports: set the port field to match your web UI port

---

## Proxmox VE Integration

Collects Proxmox VE configuration files over SSH/SFTP and stores them as a tar.gz archive — no API token needed. Symbolic links are preserved.

### What is Collected

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

1. **Add credential:** `root` (or SSH user with read access to `/etc/pve`)
2. **Add device:** Engine: `Proxmox VE (SSH/SFTP)`, Port: 22
3. **Run backup** — files collected via SFTP, packed into tar.gz, saved to backup directory

### Viewing Backups

- Backups list shows an archive icon for Proxmox backups
- Click to open the **file browser** with all collected files
- **Eye icon** — view file contents inline
- **Download icon** — download a single file
- **Download archive** — download the full tar.gz

### Proxmox Notes

- Missing paths are silently skipped (not all systems have all files)
- Change detection via SHA256 hash of the full archive
- Archives stored in the backup directory under `<hostname>/`

---

## MikroTik RouterOS

MikroTik routers are backed up via SSH using the `/export` command, which outputs the full RouterOS configuration.

### Setup

1. **Add credential:** SSH username and password (no enable secret needed)
2. **Add device:** Type: `MikroTik RouterOS`, Engine: `Netmiko (SSH)`, Port: 22
3. **Run backup** — fetches the full config via `/export`

### Notes

- Uses Netmiko's native `mikrotik_routeros` SSH driver
- No enable secret required — MikroTik does not use privileged exec mode
- SSH must be enabled on the router (`/ip service enable ssh`)
- The backup user needs at least `read` and `sensitive` policies to export the full config
- For RouterOS v7+, ensure the user has the `rest-api` policy if using API access elsewhere

### Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| **Authentication failed** | Wrong credentials or SSH disabled | Verify SSH is enabled: `/ip service print` |
| **Timeout** | Firewall blocking port 22 | Check `/ip firewall filter` rules |
| **Empty output** | User lacks permissions | Ensure user has `read` and `sensitive` policies |

---

## Nokia SR OS Notes

Nokia SR OS devices (7750, 7210, 7250 IXR, 7450, 7705 SAR) require extra connection timing. VIBENetBackup automatically applies `global_delay_factor=2` and extended timeouts.

### Classic CLI vs MD-CLI

| CLI Mode | Device Type | Config Command | Prompt Format |
|----------|-------------|----------------|---------------|
| Classic (pre-16.0) | `nokia_sros` | `admin display-config` | `*A:hostname#` |
| MD-CLI (16.0+) | `nokia_sros_md` | `admin show configuration` | `[/]A:admin@hostname#` |

**How to check which mode your device uses:**
```
# Classic CLI prompt:
*A:sar7705-rr51#

# MD-CLI prompt:
[/]
A:admin@sar7705-rr51#
```

### Nokia Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| **Pattern not detected** | Wrong CLI mode selected | Verify classic vs MD-CLI and update device type |
| **Timeout after auth** | Slow prompt | Handled automatically with `global_delay_factor=2` |
| **Wrong config output** | Classic command on MD-CLI device | Change device type accordingly |

---

## Git Destinations

Push backups to GitHub, Gitea, Forgejo, or any Git remote. Supports private repos.

### Auth Methods

| Method | Config JSON |
|--------|-------------|
| **Token (HTTPS)** | `{"auth_method": "token", "token": "ghp_...", "remote_url": "https://github.com/org/repo.git"}` |
| **SSH key** | `{"auth_method": "ssh", "ssh_key_path": "/app/ssh_keys/id_ed25519", "remote_url": "git@github.com:org/repo.git"}` |
| **Username/Password** | `{"auth_method": "password", "username": "...", "password": "...", "remote_url": "https://gitea.local/org/repo.git"}` |

All methods also require `repo_path` (local clone path) and optionally `branch` (defaults to `main`).

For Docker, SSH keys go in the `./ssh_keys` volume mounted at `/app/ssh_keys`.
