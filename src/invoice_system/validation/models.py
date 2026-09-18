"""Typed contracts shared by validation stages."""

from enum import Enum

from pydantic import BaseModel, Field

from invoice_system.ingestion.models import IngestionResult


class ValidationStage(str, Enum):
    SEMANTIC = "semantic"


class SemanticStatus(str, Enum):
    PASS = "PASS"
    DENY = "DENY"


class CriticDecision(str, Enum):
    AGREE = "AGREE"
    REVISE = "REVISE"


class ValidationStatus(str, Enum):
    VALID = "VALID"
    DENIED = "DENIED"


class IssueSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


class ValidationIssue(BaseModel):
    """A concise, auditable semantic finding."""

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    field: str | None = None
    severity: IssueSeverity = IssueSeverity.ERROR
    evidence: list[str] = Field(default_factory=list)


class SemanticResult(BaseModel):
    stage: ValidationStage = ValidationStage.SEMANTIC
    status: SemanticStatus
    issues: list[ValidationIssue] = Field(default_factory=list)
    summary: str = Field(min_length=1)


class CriticResult(BaseModel):
    decision: CriticDecision
    findings: list[ValidationIssue] = Field(default_factory=list)
    revision_instructions: str | None = None
    summary: str = Field(min_length=1)


class ValidationResult(BaseModel):
    status: ValidationStatus
    reason: str
    denied_by: ValidationStage | None = None
    issues: list[ValidationIssue] = Field(default_factory=list)
    semantic_result: SemanticResult
    critic_result: CriticResult
    ingestion: IngestionResult
