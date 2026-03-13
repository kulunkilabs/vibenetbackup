from abc import ABC, abstractmethod
from typing import Any


class DestinationBackend(ABC):
    @abstractmethod
    async def save(self, hostname: str, config_text: str, config: dict[str, Any]) -> str:
        """Save config and return the path/location where it was stored."""
        pass

    @abstractmethod
    async def delete(self, path: str, config: dict[str, Any]) -> None:
        """Delete a backup at the given path."""
        pass
