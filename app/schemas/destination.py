from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, Any
from app.models.destination import DestinationType


class DestinationBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    dest_type: DestinationType
    config_json: Optional[dict[str, Any]] = None
    enabled: bool = True
    retention_config: Optional[dict[str, int]] = None


class DestinationCreate(DestinationBase):
    pass


class DestinationUpdate(BaseModel):
    name: Optional[str] = None
    dest_type: Optional[DestinationType] = None
    config_json: Optional[dict[str, Any]] = None
    enabled: Optional[bool] = None
    retention_config: Optional[dict[str, int]] = None


class DestinationRead(DestinationBase):
    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
