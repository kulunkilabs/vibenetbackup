from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

from app.database import Base


# ── Device type registry ──────────────────────────────────────────────
# Maps Netmiko device_type string -> display label.
# To add a new vendor, just add a row here. No migration needed.
DEVICE_TYPES: dict[str, str] = {
    # Brocade / Ruckus
    "ruckus_fastiron":      "Ruckus ICX / FastIron",
    # Cisco
    "cisco_ios":            "Cisco IOS",
    "cisco_nxos":           "Cisco NX-OS",
    "cisco_xe":             "Cisco IOS-XE",
    "cisco_xr":             "Cisco IOS-XR",
    "cisco_asa":            "Cisco ASA",
    # Nokia
    "nokia_sros":           "Nokia SR OS Classic CLI (7750 / 7210 / 7250 IXR / 7450 / 7705)",
    "nokia_sros_md":        "Nokia SR OS MD-CLI (7750 / 7210 / 7250 IXR / 7450 / 7705)",
    # Nuage / Nokia SD-WAN
    "linux":                "Nuage VSC (TiMOS/Linux)",
    # HP / Aruba
    "hp_procurve":          "HP ProCurve / Aruba OS-Switch",
    "hp_comware":           "HP Comware (A/H3C)",
    "aruba_osswitch":       "Aruba OS-CX",
    # Dell
    "dell_force10":         "Dell Force10 (FTOS)",
    "dell_os6":             "Dell OS6 (N-series)",
    "dell_os9":             "Dell OS9 (S/Z-series)",
    "dell_os10":            "Dell OS10",
    "dell_powerconnect":    "Dell PowerConnect",
    # Quanta / QuantaMesh
    "quanta_mesh":          "QuantaMesh (FASTPATH)",
    # Arista
    "arista_eos":           "Arista EOS",
    # Juniper
    "juniper_junos":        "Juniper JunOS",
    # pfSense / OPNsense (FreeBSD-based)
    "pfsense":              "pfSense Firewall (FreeBSD)",
    "opnsense":             "OPNsense Firewall (FreeBSD)",
    # MikroTik
    "mikrotik_routeros":    "MikroTik RouterOS",
    # Proxmox VE
    "proxmox":              "Proxmox VE (config file backup)",
    # Generic
    "linux":                "Linux (generic SSH)",
    "generic":              "Generic (autodetect)",
}

# ── Per-device-type config fetch commands ─────────────────────────────
# Each entry is a list of commands; outputs are concatenated.
DEVICE_COMMANDS: dict[str, list[str]] = {
    # Brocade / Ruckus
    "ruckus_fastiron":      ["show running-config"],
    # Cisco
    "cisco_ios":            ["show running-config"],
    "cisco_nxos":           ["show running-config"],
    "cisco_xe":             ["show running-config"],
    "cisco_xr":             ["show running-config"],
    "cisco_asa":            ["show running-config"],
    # Nokia SROS  (classic CLI)
    "nokia_sros":           ["admin display-config"],
    # Nokia SROS  (model-driven CLI — 16.0+)
    "nokia_sros_md":        ["admin show configuration"],
    # Nuage VSC runs TiMOS under the hood
    "linux":                ["cat /etc/network/interfaces"],
    # HP
    "hp_procurve":          ["show running-config"],
    "hp_comware":           ["display current-configuration"],
    "aruba_osswitch":       ["show running-config"],
    # Dell
    "dell_force10":         ["show running-config"],
    "dell_os6":             ["show running-config"],
    "dell_os9":             ["show running-config"],
    "dell_os10":            ["show running-configuration"],
    "dell_powerconnect":    ["show running-config"],
    # Quanta
    "quanta_mesh":          ["show running-config"],
    # Arista
    "arista_eos":           ["show running-config"],
    # Juniper
    "juniper_junos":        ["show configuration | display set"],
    # MikroTik
    "mikrotik_routeros":    ["/export"],
    # pfSense / OPNsense (SSH fallback)
    "pfsense":              ["cat /cf/conf/config.xml"],
    "opnsense":             ["cat /conf/config.xml"],
    # Fallback
    "generic":              ["show running-config"],
}


# ── Oxidized model name  →  Netmiko device_type ──────────────────────
# Oxidized uses its own model names (shown in nodes.json).
# This maps them to our Netmiko device_type strings.
# Anything not in here gets stored as-is (you can still back up via oxidized engine).
OXIDIZED_MODEL_MAP: dict[str, str] = {
    # Brocade / Ruckus
    "ironware":         "ruckus_fastiron",
    "fastiron":         "ruckus_fastiron",
    # Cisco
    "ios":              "cisco_ios",
    "iosxe":            "cisco_xe",
    "iosxr":            "cisco_xr",
    "nxos":             "cisco_nxos",
    "asa":              "cisco_asa",
    "catos":            "cisco_ios",
    # Nokia / ALU
    "alusr":            "nokia_sros",       # Oxidized uses "alusr" for SROS classic
    "sros":             "nokia_sros",
    "timosmda":         "nokia_sros_md",
    "timos":            "nokia_sros",
    # Nuage
    "vsc":              "linux",
    # HP / Aruba
    "procurve":         "hp_procurve",
    "comware":          "hp_comware",
    "arubaos":          "hp_procurve",
    "aoscx":            "aruba_osswitch",
    # Dell
    "ftos":             "dell_force10",
    "dell_os10":        "dell_os10",
    "powerconnect":     "dell_powerconnect",
    "dnos6":            "dell_os6",
    "dnos9":            "dell_os9",
    "dnos10":           "dell_os10",
    # Quanta
    "quantaos":         "quanta_mesh",
    "quanta":           "quanta_mesh",
    # Arista
    "eos":              "arista_eos",
    # Juniper
    "junos":            "juniper_junos",
    # pfSense / OPNsense
    "pfsense":          "pfsense",
    "opnsense":         "opnsense",
    # Palo Alto
    "panos":            "paloalto_panos",
    # Fortinet
    "fortios":          "fortinet",
    # MikroTik
    "routeros":         "mikrotik_routeros",
    # Linux
    "linux":            "linux",
}


def oxidized_model_to_device_type(model: str) -> str:
    """Convert an Oxidized model name to a Netmiko device_type. Returns as-is if unknown."""
    return OXIDIZED_MODEL_MAP.get(model.lower(), model.lower())


# ── Netmiko device type mapping ────────────────────────────────────────
# Maps our device_type to Netmiko's device_type string.
# Some devices (like pfSense/OPNsense) need to use generic SSH types.
NETMIKO_DEVICE_TYPE_MAP: dict[str, str] = {
    "nokia_sros_md": "nokia_sros",  # MD-CLI uses same SSH driver, different commands
    "pfsense":       "linux",       # FreeBSD - use generic Linux/SSH type
    "opnsense":      "linux",       # FreeBSD - use generic Linux/SSH type
}


# Default ports per engine type (SSH=22, web API=443)
ENGINE_DEFAULT_PORTS: dict[str, int] = {
    "netmiko": 22,
    "scp": 22,
    "oxidized": 8888,
    "pfsense": 443,
    "proxmox": 22,
}


def get_engine_default_port(engine: str) -> int:
    """Return the default port for a given backup engine."""
    return ENGINE_DEFAULT_PORTS.get(engine, 22)


def get_netmiko_device_type(device_type: str) -> str:
    """Get the Netmiko device_type string for our device_type."""
    return NETMIKO_DEVICE_TYPE_MAP.get(device_type, device_type)


def get_config_commands(device_type: str) -> list[str]:
    """Return the list of CLI commands to fetch config for a device type."""
    return DEVICE_COMMANDS.get(device_type, ["show running-config"])


class Device(Base):
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, index=True)
    hostname = Column(String(255), nullable=False, index=True)
    ip_address = Column(String(45), nullable=False)
    # Free-form string so new types need no DB migration — just add to DEVICE_TYPES
    device_type = Column(String(50), nullable=False, default="ruckus_fastiron")
    credential_id = Column(Integer, ForeignKey("credentials.id"), nullable=True)
    group = Column(String(100), nullable=True, default="default")
    enabled = Column(Boolean, default=True)
    backup_engine = Column(String(50), nullable=False, default="netmiko")
    port = Column(Integer, default=22)
    proxy_host = Column(String(255), nullable=True)
    proxy_port = Column(Integer, nullable=True)
    notes = Column(String(1000), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    credential = relationship("Credential", back_populates="devices")
    backups = relationship("Backup", back_populates="device", cascade="all, delete-orphan")
