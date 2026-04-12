from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class CredentialBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    username: Optional[str] = Field(None, max_length=255)
    ssh_key_path: Optional[str] = None


class CredentialCreate(CredentialBase):
    password: Optional[str] = None
    enable_secret: Optional[str] = None


class CredentialUpdate(BaseModel):
    name: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    enable_secret: Optional[str] = None
    ssh_key_path: Optional[str] = None


class CredentialRead(BaseModel):
    id: int
    name: str
    username: Optional[str] = None
    ssh_key_path: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # password is never exposed

    model_config = {"from_attributes": True}
