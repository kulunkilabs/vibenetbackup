from app.modules.destinations.base import DestinationBackend
from app.modules.destinations.local import LocalDestination
from app.modules.destinations.forgejo import ForgejoDestination
from app.modules.destinations.smb import SMBDestination

DESTINATIONS: dict[str, type[DestinationBackend]] = {
    "local": LocalDestination,
    "forgejo": ForgejoDestination,
    "smb": SMBDestination,
}


def get_destination(name: str) -> DestinationBackend:
    cls = DESTINATIONS.get(name)
    if cls is None:
        raise ValueError(f"Unknown destination type: {name}")
    return cls()
