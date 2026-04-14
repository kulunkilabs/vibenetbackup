import base64
import hashlib

from sqlalchemy import Column, Integer, String, Boolean, DateTime
from datetime import datetime, timezone
from cryptography.fernet import Fernet

from app.database import Base
from app.config import get_settings


class NotificationChannel(Base):
    __tablename__ = "notification_channels"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, unique=True)
    apprise_url_encrypted = Column(String(1000), nullable=False)
    enabled = Column(Boolean, default=True)
    on_success = Column(Boolean, default=False)
    on_failure = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    @staticmethod
    def _get_fernet() -> Fernet:
        secret = get_settings().SECRET_KEY.encode()
        key = base64.urlsafe_b64encode(hashlib.sha256(secret).digest())
        return Fernet(key)

    def set_url(self, plain: str) -> None:
        self.apprise_url_encrypted = self._get_fernet().encrypt(plain.encode()).decode()

    def get_url(self) -> str:
        return self._get_fernet().decrypt(self.apprise_url_encrypted.encode()).decode()
