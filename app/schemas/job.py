from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional
from app.models.job import JobStatus


class ScheduleBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    cron_expression: str = Field(..., min_length=1, max_length=100)
    device_ids: Optional[list[int]] = None
    device_group: Optional[str] = None
    backup_engine: Optional[str] = None
    destination_ids: Optional[list[int]] = None
    enabled: bool = True


class ScheduleCreate(ScheduleBase):
    pass


class ScheduleUpdate(BaseModel):
    name: Optional[str] = None
    cron_expression: Optional[str] = None
    device_ids: Optional[list[int]] = None
    device_group: Optional[str] = None
    backup_engine: Optional[str] = None
    destination_ids: Optional[list[int]] = None
    enabled: Optional[bool] = None


class ScheduleRead(ScheduleBase):
    id: int
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class JobRunRead(BaseModel):
    id: int
    job_name: str
    schedule_id: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    status: JobStatus
    devices_total: int = 0
    devices_success: int = 0
    devices_failed: int = 0
    error_log: Optional[str] = None

    model_config = {"from_attributes": True}
