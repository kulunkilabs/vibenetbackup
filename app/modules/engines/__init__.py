from app.modules.engines.base import BackupEngine
from app.modules.engines.netmiko_engine import NetmikoEngine
from app.modules.engines.scp_engine import SCPEngine
from app.modules.engines.oxidized_engine import OxidizedEngine
from app.modules.engines.pfsense_engine import PfSenseEngine

ENGINES: dict[str, type[BackupEngine]] = {
    "netmiko": NetmikoEngine,
    "scp": SCPEngine,
    "oxidized": OxidizedEngine,
    "pfsense": PfSenseEngine,
}


def get_engine(name: str) -> BackupEngine:
    cls = ENGINES.get(name)
    if cls is None:
        raise ValueError(f"Unknown backup engine: {name}")
    return cls()
