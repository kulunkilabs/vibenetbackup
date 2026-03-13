import asyncio
import io
import logging
import zipfile

import paramiko

from app.modules.engines.base import BackupEngine
from app.models.device import Device
from app.models.credential import Credential

logger = logging.getLogger(__name__)

# Files and directories to collect from each Proxmox node.
# Paths that don't exist on a given host are silently skipped.
PROXMOX_BACKUP_PATHS = [
    # ── Proxmox VE core ───────────────────────────────────────────────
    "/etc/pve",                         # ALL PVE config: VMs, LXC, storage, users, firewall, cluster
    "/etc/vzdump.conf",                 # backup job settings

    # ── Network ───────────────────────────────────────────────────────
    "/etc/network/interfaces",
    "/etc/network/interfaces.d",

    # ── Identity / DNS ────────────────────────────────────────────────
    "/etc/hostname",
    "/etc/hosts",
    "/etc/resolv.conf",

    # ── SSH ───────────────────────────────────────────────────────────
    "/root/.ssh",
    "/etc/ssh/sshd_config",
    "/etc/ssh/ssh_config",
    "/etc/ssh/sshd_config.d",

    # ── Scheduled tasks ───────────────────────────────────────────────
    "/etc/cron.d",
    "/etc/cron.daily",
    "/etc/cron.weekly",
    "/etc/cron.monthly",
    "/etc/cron.hourly",
    "/var/spool/cron/crontabs",

    # ── Storage ───────────────────────────────────────────────────────
    "/etc/fstab",
    "/etc/crypttab",
    "/etc/lvm/lvm.conf",
    "/etc/multipath.conf",
    "/etc/multipath",
    "/etc/iscsi",
    "/etc/zfs",

    # ── Ceph (if used) ────────────────────────────────────────────────
    "/etc/ceph",

    # ── Proxmox Backup Server client ──────────────────────────────────
    "/etc/proxmox-backup",
    "/etc/proxmox-backup-client",

    # ── Kernel / boot ─────────────────────────────────────────────────
    "/etc/default/grub",
    "/etc/default/grub.d",
    "/etc/modprobe.d",
    "/etc/modules-load.d",
    "/etc/modules",
    "/etc/sysctl.conf",
    "/etc/sysctl.d",

    # ── Firewall / security ───────────────────────────────────────────
    "/etc/nftables.conf",
    "/etc/fail2ban",

    # ── APT / package sources ─────────────────────────────────────────
    "/etc/apt/sources.list",
    "/etc/apt/sources.list.d",
    "/etc/apt/auth.conf.d",

    # ── System logging ────────────────────────────────────────────────
    "/etc/rsyslog.conf",
    "/etc/rsyslog.d",
    "/etc/logrotate.conf",
    "/etc/logrotate.d",

    # ── Mail (for alerts) ─────────────────────────────────────────────
    "/etc/postfix/main.cf",
    "/etc/postfix/master.cf",

    # ── Time sync ─────────────────────────────────────────────────────
    "/etc/chrony/chrony.conf",
    "/etc/ntp.conf",
    "/etc/systemd/timesyncd.conf",

    # ── PAM / authentication ──────────────────────────────────────────
    "/etc/pam.d",
    "/etc/security",
    "/etc/nsswitch.conf",
    "/etc/ldap",
    "/etc/sssd",

    # ── Custom systemd units ──────────────────────────────────────────
    "/etc/systemd/system",

    # ── udev device rules ─────────────────────────────────────────────
    "/etc/udev/rules.d",

    # ── Custom scripts ────────────────────────────────────────────────
    "/usr/local/bin",
    "/usr/local/sbin",

    # ── Root shell / environment ──────────────────────────────────────
    "/root/.bashrc",
    "/root/.bash_profile",
    "/root/.profile",
    "/root/.bash_aliases",
]


def _ssh_connect(device: Device, credential: Credential) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kwargs: dict = {
        "hostname": device.ip_address,
        "port": device.port or 22,
        "username": credential.username,
        "timeout": 30,
    }
    ssh_key_path = getattr(credential, "ssh_key_path", None)
    if ssh_key_path:
        kwargs["key_filename"] = ssh_key_path
    else:
        kwargs["password"] = credential.get_password()
    client.connect(**kwargs)
    return client


def _collect_zip(sftp: paramiko.SFTPClient, paths: list[str]) -> tuple[bytes, list[str]]:
    """Walk each path over SFTP and pack everything into an in-memory ZIP."""
    buf = io.BytesIO()
    collected: list[str] = []

    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for remote_path in paths:
            try:
                stat = sftp.stat(remote_path)
            except FileNotFoundError:
                logger.debug("Proxmox SFTP: not found, skipping: %s", remote_path)
                continue

            import stat as stat_mod
            if stat_mod.S_ISDIR(stat.st_mode):
                _add_dir(sftp, zf, remote_path, collected)
            else:
                _add_file(sftp, zf, remote_path, collected)

    return buf.getvalue(), collected


def _add_dir(
    sftp: paramiko.SFTPClient,
    zf: zipfile.ZipFile,
    remote_dir: str,
    collected: list[str],
) -> None:
    try:
        entries = sftp.listdir_attr(remote_dir)
    except Exception as e:
        logger.warning("Proxmox SFTP: cannot list %s: %s", remote_dir, e)
        return

    import stat as stat_mod
    for entry in entries:
        remote_path = f"{remote_dir}/{entry.filename}"
        if stat_mod.S_ISDIR(entry.st_mode):
            _add_dir(sftp, zf, remote_path, collected)
        else:
            _add_file(sftp, zf, remote_path, collected)


def _add_file(
    sftp: paramiko.SFTPClient,
    zf: zipfile.ZipFile,
    remote_path: str,
    collected: list[str],
) -> None:
    try:
        file_buf = io.BytesIO()
        sftp.getfo(remote_path, file_buf)
        arc_name = remote_path.lstrip("/")
        zf.writestr(arc_name, file_buf.getvalue())
        collected.append(arc_name)
        logger.debug("Proxmox SFTP: added %s (%d bytes)", remote_path, file_buf.tell())
    except Exception as e:
        logger.warning("Proxmox SFTP: cannot fetch %s: %s", remote_path, e)


def _fetch_zip(device: Device, credential: Credential) -> tuple[bytes, list[str]]:
    client = _ssh_connect(device, credential)
    try:
        sftp = client.open_sftp()
        try:
            return _collect_zip(sftp, PROXMOX_BACKUP_PATHS)
        finally:
            sftp.close()
    finally:
        client.close()


def _test(device: Device, credential: Credential) -> bool:
    client = _ssh_connect(device, credential)
    client.close()
    return True


class ProxmoxEngine(BackupEngine):
    """
    Backup engine for Proxmox VE nodes.

    Connects via SSH/SFTP, downloads all critical configuration paths
    and packages them as a ZIP archive. Each file is individually accessible
    from the dashboard and can be downloaded separately.
    """

    async def fetch_binary(
        self, device: Device, credential: Credential
    ) -> tuple[bytes, str, list[str]] | None:
        logger.info(
            "Proxmox: starting file collection from %s (%s)",
            device.hostname, device.ip_address,
        )
        try:
            zip_bytes, file_list = await asyncio.to_thread(_fetch_zip, device, credential)
            logger.info(
                "Proxmox: collected %d files from %s, ZIP size %d bytes",
                len(file_list), device.hostname, len(zip_bytes),
            )
            return zip_bytes, ".zip", file_list
        except paramiko.AuthenticationException:
            raise PermissionError(
                f"Proxmox SSH auth failed for {device.hostname} ({device.ip_address})"
            )
        except Exception as e:
            raise RuntimeError(f"Proxmox backup error on {device.hostname}: {e}")

    async def fetch_config(self, device: Device, credential: Credential) -> str:
        # fetch_binary is the primary method; this is a fallback stub
        raise NotImplementedError("ProxmoxEngine uses fetch_binary()")

    async def test_connection(self, device: Device, credential: Credential) -> bool:
        logger.info(
            "Proxmox: testing SSH connection to %s (%s)",
            device.hostname, device.ip_address,
        )
        try:
            return await asyncio.to_thread(_test, device, credential)
        except Exception as e:
            logger.warning(
                "Proxmox: connection test failed for %s: %s", device.hostname, e
            )
            return False
