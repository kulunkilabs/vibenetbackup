from sqlalchemy import Column, Integer, String, DateTime, Text, JSON, Boolean, Enum as SAEnum
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import enum

from app.database import Base


class JobStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class JobRun(Base):
    __tablename__ = "job_runs"

    id = Column(Integer, primary_key=True, index=True)
    job_name = Column(String(255), nullable=False)
    schedule_id = Column(Integer, nullable=True)
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    completed_at = Column(DateTime, nullable=True)
    status = Column(SAEnum(JobStatus), nullable=False, default=JobStatus.pending)
    devices_total = Column(Integer, default=0)
    devices_success = Column(Integer, default=0)
    devices_failed = Column(Integer, default=0)
    error_log = Column(Text, nullable=True)

    backups = relationship("Backup", back_populates="job_run")


class Schedule(Base):
    __tablename__ = "schedules"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, unique=True)
    cron_expression = Column(String(100), nullable=False)  # e.g. "0 2 * * *"
    device_ids = Column(JSON, nullable=True)  # list of device IDs
    device_group = Column(String(100), nullable=True)  # or backup by group
    backup_engine = Column(String(50), nullable=True)  # override engine
    destination_ids = Column(JSON, nullable=True)  # list of destination IDs
    enabled = Column(Boolean, default=True)
    last_run_at = Column(DateTime, nullable=True)
    next_run_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
