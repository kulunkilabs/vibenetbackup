from sqlalchemy import Column, Integer, String, DateTime, JSON
from datetime import datetime, timezone
from app.database import Base


class Group(Base):
    __tablename__ = "groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(String(500), nullable=True)
    # Profile fields
    destination_ids = Column(JSON, nullable=True)       # list of destination IDs
    backup_engine = Column(String(50), nullable=True)   # engine override (optional)
    notification_ids = Column(JSON, nullable=True)       # notification channel IDs (optional)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
