from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class ConfidenceLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class IncidentRequest(BaseModel):
    service: str
    environment: Optional[str] = None
    api_path: Optional[str] = Field(default=None, alias="apiPath")
    http_status: Optional[int] = Field(default=None, alias="httpStatus")
    error_message: Optional[str] = Field(default=None, alias="errorMessage")
    stack_trace: str = Field(alias="stackTrace")
    recent_logs: Optional[str] = Field(default=None, alias="recentLogs")
    related_services: List[str] = Field(default_factory=list, alias="relatedServices")

    model_config = {"populate_by_name": True}


class AffectedFile(BaseModel):
    repo: str
    path: str
    lines: str


class DiagnosisResponse(BaseModel):
    root_cause: str = Field(alias="rootCause")
    confidence: ConfidenceLevel
    affected_files: List[AffectedFile] = Field(default_factory=list, alias="affectedFiles")
    suggested_fix: str = Field(alias="suggestedFix")
    reasoning_steps: List[str] = Field(default_factory=list, alias="reasoningSteps")
    related_incidents: List[str] = Field(default_factory=list, alias="relatedIncidents")

    model_config = {"populate_by_name": True}
