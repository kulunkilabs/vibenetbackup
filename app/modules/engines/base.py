from abc import ABC, abstractmethod
from app.models.device import Device
from app.models.credential import Credential


class BackupEngine(ABC):
    @abstractmethod
    async def fetch_config(self, device: Device, credential: Credential) -> str:
        """Fetch running config from device, return as string."""
        pass

    @abstractmethod
    async def test_connection(self, device: Device, credential: Credential) -> bool:
        """Test if device is reachable and credentials work."""
        pass

    async def fetch_binary(
        self, device: Device, credential: Credential
    ) -> tuple[bytes, str, list[str]] | None:
        """
        Optional: return (file_bytes, extension, file_list) for binary backups.
        - file_bytes: raw binary content (e.g. ZIP)
        - extension:  file extension including dot (e.g. ".zip")
        - file_list:  list of filenames inside the archive for the manifest
        Returns None if this engine only supports text config.
        """
        return None
