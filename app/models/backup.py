from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean, Enum as SAEnum
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import enum

from app.database import Base


class BackupStatus(str, enum.Enum):
    success = "success"
    failed = "failed"
    unchanged = "unchanged"
    in_progress = "in_progress"


class Backup(Base):
    __tablename__ = "backups"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), index=True)
    config_text = Column(Text, nullable=True)
    config_hash = Column(String(64), nullable=True)  # SHA256
    destination_type = Column(String(50), nullable=True)
    destination_path = Column(String(500), nullable=True)
    file_size = Column(Integer, nullable=True)
    status = Column(SAEnum(BackupStatus), nullable=False, default=BackupStatus.in_progress)
    error_message = Column(Text, nullable=True)
    retention_tier = Column(String(20), nullable=True)  # daily, weekly, monthly
    is_pruned = Column(Boolean, default=False)
    pruned_at = Column(DateTime, nullable=True)
    job_run_id = Column(Integer, ForeignKey("job_runs.id"), nullable=True)

    device = relationship("Device", back_populates="backups")
    job_run = relationship("JobRun", back_populates="backups")
