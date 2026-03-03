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
