from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class DeviceBase(BaseModel):
    hostname: str = Field(..., min_length=1, max_length=255)
    ip_address: str = Field(..., min_length=1, max_length=45)
    device_type: str = "ruckus_fastiron"
    credential_id: Optional[int] = None
    group: str = "default"
    enabled: bool = True
    backup_engine: str = "netmiko"
    port: int = 22
    notes: Optional[str] = None


class DeviceCreate(DeviceBase):
    pass


class DeviceUpdate(BaseModel):
    hostname: Optional[str] = None
    ip_address: Optional[str] = None
    device_type: Optional[str] = None
    credential_id: Optional[int] = None
    group: Optional[str] = None
    enabled: Optional[bool] = None
    backup_engine: Optional[str] = None
    port: Optional[int] = None
    notes: Optional[str] = None


class DeviceRead(DeviceBase):
    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
