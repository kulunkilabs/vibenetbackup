from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from app.models.backup import BackupStatus


class BackupTrigger(BaseModel):
    device_ids: list[int]
    destination_ids: Optional[list[int]] = None
    engine_override: Optional[str] = None


class BackupRead(BaseModel):
    id: int
    device_id: int
    timestamp: Optional[datetime] = None
    config_hash: Optional[str] = None
    destination_type: Optional[str] = None
    destination_path: Optional[str] = None
    file_size: Optional[int] = None
    status: BackupStatus
    error_message: Optional[str] = None
    retention_tier: Optional[str] = None
    is_pruned: bool = False
    job_run_id: Optional[int] = None

    model_config = {"from_attributes": True}


class BackupDetail(BackupRead):
    config_text: Optional[str] = None
    device_hostname: Optional[str] = None
