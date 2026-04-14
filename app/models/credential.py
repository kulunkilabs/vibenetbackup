import base64
import hashlib

from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from cryptography.fernet import Fernet

from app.database import Base
from app.config import get_settings


class Credential(Base):
    __tablename__ = "credentials"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, unique=True)
    username = Column(String(255), nullable=True)
    password_encrypted = Column(String(500), nullable=True)
    enable_secret_encrypted = Column(String(500), nullable=True)
    ssh_key_path = Column(String(500), nullable=True)
    group = Column(String(100), nullable=True, default="default")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    devices = relationship("Device", foreign_keys="Device.credential_id", back_populates="credential")

    @staticmethod
    def _get_fernet() -> Fernet:
        secret = get_settings().SECRET_KEY.encode()
        # Derive a valid 32-byte Fernet key from the SECRET_KEY
        key = base64.urlsafe_b64encode(hashlib.sha256(secret).digest())
        return Fernet(key)

    def set_password(self, plain: str) -> None:
        self.password_encrypted = self._get_fernet().encrypt(plain.encode()).decode()

    def get_password(self) -> str | None:
        if not self.password_encrypted:
            return None
        return self._get_fernet().decrypt(self.password_encrypted.encode()).decode()

    def set_enable_secret(self, plain: str) -> None:
        self.enable_secret_encrypted = self._get_fernet().encrypt(plain.encode()).decode()

    def get_enable_secret(self) -> str | None:
        if not self.enable_secret_encrypted:
            return None
        return self._get_fernet().decrypt(self.enable_secret_encrypted.encode()).decode()
