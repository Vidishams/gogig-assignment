import uuid
import enum
from datetime import datetime, timezone

from sqlalchemy import Column, String, DateTime, ForeignKey, Float, Boolean, JSON, Enum
from sqlalchemy.dialects.postgresql import UUID

from common.database import Base


class ImageStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class Image(Base):
    __tablename__ = "images"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename = Column(String, nullable=False)
    storage_path = Column(String, nullable=False)
    phash = Column(String, nullable=True, index=True)
    status = Column(Enum(ImageStatus), default=ImageStatus.pending, nullable=False)
    failure_reason = Column(String, nullable=True)
    uploaded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    processed_at = Column(DateTime, nullable=True)


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    image_id = Column(UUID(as_uuid=True), ForeignKey("images.id"), nullable=False, index=True)
    check_name = Column(String, nullable=False)
    passed = Column(Boolean, nullable=False)
    confidence = Column(Float, nullable=False)
    details = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
