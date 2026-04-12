import asyncio
import io
import logging
import stat as stat_mod
import tarfile

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
    if not credential.username:
        raise ValueError(f"Credential '{credential.name}' has no username — SSH requires a username")
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


def _collect_tgz(sftp: paramiko.SFTPClient, paths: list[str]) -> tuple[bytes, list[str]]:
    """Walk each path over SFTP and pack everything into an in-memory tar.gz.

    Preserves symbolic links as symlinks inside the archive.
    """
    buf = io.BytesIO()
    collected: list[str] = []

    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for remote_path in paths:
            try:
                attr = sftp.lstat(remote_path)
            except FileNotFoundError:
                logger.debug("Proxmox SFTP: not found, skipping: %s", remote_path)
                continue

            if stat_mod.S_ISDIR(attr.st_mode):
                _add_dir_tar(sftp, tf, remote_path, collected)
            elif stat_mod.S_ISLNK(attr.st_mode):
                _add_symlink_tar(sftp, tf, remote_path, collected)
            else:
                _add_file_tar(sftp, tf, remote_path, attr, collected)

    return buf.getvalue(), collected


def _add_dir_tar(
    sftp: paramiko.SFTPClient,
    tf: tarfile.TarFile,
    remote_dir: str,
    collected: list[str],
) -> None:
    try:
        entries = sftp.listdir_attr(remote_dir)
    except Exception as e:
        logger.warning("Proxmox SFTP: cannot list %s: %s", remote_dir, e)
        return

    for entry in entries:
        remote_path = f"{remote_dir}/{entry.filename}"
        if stat_mod.S_ISDIR(entry.st_mode):
            _add_dir_tar(sftp, tf, remote_path, collected)
        elif stat_mod.S_ISLNK(entry.st_mode):
            _add_symlink_tar(sftp, tf, remote_path, collected)
        else:
            _add_file_tar(sftp, tf, remote_path, entry, collected)


def _add_symlink_tar(
    sftp: paramiko.SFTPClient,
    tf: tarfile.TarFile,
    remote_path: str,
    collected: list[str],
) -> None:
    try:
        link_target = sftp.readlink(remote_path)
        arc_name = remote_path.lstrip("/")
        info = tarfile.TarInfo(name=arc_name)
        info.type = tarfile.SYMTYPE
        info.linkname = link_target
        tf.addfile(info)
        collected.append(arc_name)
        logger.debug("Proxmox SFTP: added symlink %s -> %s", remote_path, link_target)
    except Exception as e:
        logger.warning("Proxmox SFTP: cannot read symlink %s: %s", remote_path, e)


def _add_file_tar(
    sftp: paramiko.SFTPClient,
    tf: tarfile.TarFile,
    remote_path: str,
    attr,
    collected: list[str],
) -> None:
    try:
        file_buf = io.BytesIO()
        sftp.getfo(remote_path, file_buf)
        file_buf.seek(0)
        arc_name = remote_path.lstrip("/")
        info = tarfile.TarInfo(name=arc_name)
        info.size = file_buf.getbuffer().nbytes
        info.mode = attr.st_mode & 0o777
        info.uid = attr.st_uid if attr.st_uid else 0
        info.gid = attr.st_gid if attr.st_gid else 0
        tf.addfile(info, file_buf)
        collected.append(arc_name)
        logger.debug("Proxmox SFTP: added %s (%d bytes)", remote_path, info.size)
    except Exception as e:
        logger.warning("Proxmox SFTP: cannot fetch %s: %s", remote_path, e)


def _fetch_tgz(device: Device, credential: Credential) -> tuple[bytes, list[str]]:
    client = _ssh_connect(device, credential)
    try:
        sftp = client.open_sftp()
        try:
            return _collect_tgz(sftp, PROXMOX_BACKUP_PATHS)
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
    and packages them as a tar.gz archive. Symbolic links are preserved.
    Each file is individually accessible from the dashboard.
    """

    async def fetch_binary(
        self, device: Device, credential: Credential
    ) -> tuple[bytes, str, list[str]] | None:
        logger.info(
            "Proxmox: starting file collection from %s (%s)",
            device.hostname, device.ip_address,
        )
        try:
            tgz_bytes, file_list = await asyncio.to_thread(_fetch_tgz, device, credential)
            logger.info(
                "Proxmox: collected %d files from %s, TGZ size %d bytes",
                len(file_list), device.hostname, len(tgz_bytes),
            )
            return tgz_bytes, ".tar.gz", file_list
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
