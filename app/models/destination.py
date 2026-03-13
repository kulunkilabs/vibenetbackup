from sqlalchemy import Column, Integer, String, Boolean, DateTime, JSON, Enum as SAEnum
from datetime import datetime, timezone
import enum

from app.database import Base


class DestinationType(str, enum.Enum):
    local = "local"
    forgejo = "forgejo"
    smb = "smb"


class Destination(Base):
    __tablename__ = "destinations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, unique=True)
    dest_type = Column(SAEnum(DestinationType), nullable=False)
    config_json = Column(JSON, nullable=True)
    # config_json examples:
    # local: {"path": "./backups"}
    # forgejo: {"repo_path": "./repos/configs", "remote_url": "...", "branch": "main", "token": "..."}
    # smb: {"server": "...", "share": "...", "username": "...", "password": "...", "base_path": "backups"}
    enabled = Column(Boolean, default=True)
    retention_config = Column(JSON, nullable=True)
    # retention_config: {"daily": 14, "weekly": 6, "monthly": 12}
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
