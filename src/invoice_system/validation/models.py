"""Typed contracts shared by validation stages."""

from enum import Enum
from decimal import Decimal

from pydantic import BaseModel, Field

from invoice_system.ingestion.models import IngestionResult


class ValidationStage(str, Enum):
    SEMANTIC = "semantic"
    RECONCILIATION = "reconciliation"
    DATABASE = "database"


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


class ReconciliationStatus(str, Enum):
    PASS = "PASS"
    DENY = "DENY"


class ConsolidatedItem(BaseModel):
    """A deterministic, auditable product consolidation for Phase 2."""

    product_name: str = Field(min_length=1)
    normalized_product: str = Field(min_length=1)
    combined_quantity: Decimal
    source_lines: list[int] = Field(min_length=1)
    # A group-level price is meaningful only when every source line has the
    # same price. Keep all observed prices so consolidation never discards the
    # line-level arithmetic needed to reconcile an invoice.
    unit_prices: list[Decimal] = Field(default_factory=list)
    unit_price: Decimal | None = None
    derived_line_total: Decimal | None = None


class ReconciliationCheckType(str, Enum):
    LINE_TOTAL = "LINE_TOTAL"
    SUBTOTAL = "SUBTOTAL"
    TAX = "TAX"
    TOTAL = "TOTAL"


class ReconciliationCheckOutcome(str, Enum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    CALCULATED = "CALCULATED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ReconciliationCalculation(BaseModel):
    """One deterministic arithmetic check exposed by Reconciliation."""

    check_type: ReconciliationCheckType
    outcome: ReconciliationCheckOutcome
    field: str | None = None
    calculated: Decimal | None = None
    declared: Decimal | None = None
    source_lines: list[int] = Field(default_factory=list)


class ReconciliationResult(BaseModel):
    stage: ValidationStage = ValidationStage.RECONCILIATION
    status: ReconciliationStatus
    issues: list[ValidationIssue] = Field(default_factory=list)
    summary: str = Field(min_length=1)
    consolidated_items: list[ConsolidatedItem] = Field(default_factory=list)
    calculations: list[ReconciliationCalculation] = Field(default_factory=list)


class DatabaseStatus(str, Enum):
    PASS = "PASS"
    DENY = "DENY"


class DatabaseResult(BaseModel):
    """Auditable inventory outcome for one requested product."""

    requested_name: str = Field(min_length=1)
    attempted_names: list[str] = Field(min_length=1)
    normalized_product: str | None = None
    source_lines: list[int] = Field(default_factory=list)
    matched_item: str | None = None
    requested_quantity: Decimal | None = None
    available_stock: int | None = None
    product_found: bool
    inventory_sufficient: bool | None = None


class DatabaseValidationResult(BaseModel):
    """Structured result for the inventory/database validation stage."""

    stage: ValidationStage = ValidationStage.DATABASE
    status: DatabaseStatus
    issues: list[ValidationIssue] = Field(default_factory=list)
    summary: str = Field(min_length=1)
    results: list[DatabaseResult] = Field(default_factory=list)


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
    semantic_critic_result: CriticResult | None = None
    reconciliation_result: ReconciliationResult | None = None
    reconciliation_critic_result: CriticResult | None = None
    database_result: DatabaseValidationResult | None = None
    database_critic_result: CriticResult | None = None
