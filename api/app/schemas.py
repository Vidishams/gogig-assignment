import uuid
from datetime import datetime
from typing import Optional, Any

from pydantic import BaseModel


class UploadResponse(BaseModel):
    image_id: uuid.UUID
    status: str


class StatusResponse(BaseModel):
    image_id: uuid.UUID
    status: str
    uploaded_at: datetime
    processed_at: Optional[datetime] = None


class CheckResult(BaseModel):
    check_name: str
    passed: bool
    confidence: float
    details: Optional[Any] = None


class ResultsResponse(BaseModel):
    image_id: uuid.UUID
    status: str
    failure_reason: Optional[str] = None
    recommendation: Optional[str] = None
    reasoning: Optional[str] = None
    checks: list[CheckResult] = []
