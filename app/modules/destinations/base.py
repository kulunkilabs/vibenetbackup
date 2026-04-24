from abc import ABC, abstractmethod
from typing import Any


class DestinationBackend(ABC):
    @abstractmethod
    async def save(self, hostname: str, config_text: str, config: dict[str, Any]) -> str:
        """Save config and return the path/location where it was stored."""
        pass

    async def save_binary(
        self,
        hostname: str,
        data: bytes,
        extension: str,
        config: dict[str, Any],
    ) -> str:
        """Save a binary archive (e.g. .tar.gz from Proxmox) and return its path.

        Default raises NotImplementedError so callers can skip backends that
        don't make sense for archives (e.g. committing a tarball to git).
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support binary archive backups"
        )

    @abstractmethod
    async def delete(self, path: str, config: dict[str, Any]) -> None:
        """Delete a backup at the given path."""
        pass
