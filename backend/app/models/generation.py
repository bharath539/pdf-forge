"""Pydantic models for synthetic PDF generation parameters."""

from __future__ import annotations

from datetime import date
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class Scenario(str, Enum):
    SINGLE_MONTH = "single_month"
    MULTI_MONTH = "multi_month"
    MULTI_ACCOUNT = "multi_account"
    PARTIAL = "partial"
    PAST_MONTHS = "past_months"
    HIGH_VOLUME = "high_volume"
    MINIMAL = "minimal"
    ZERO_BALANCE = "zero_balance"
    NEGATIVE_BALANCE = "negative_balance"
    MULTI_PAGE = "multi_page"
    MIXED_TYPES = "mixed_types"
    INTERNATIONAL = "international"


class TransactionRange(BaseModel):
    min: int = Field(default=15, ge=1)
    max: int = Field(default=45, ge=1)


class TypeDistribution(BaseModel):
    debit_card: float = Field(default=0.4, ge=0, le=1)
    ach: float = Field(default=0.25, ge=0, le=1)
    check: float = Field(default=0.1, ge=0, le=1)
    transfer: float = Field(default=0.15, ge=0, le=1)
    atm: float = Field(default=0.1, ge=0, le=1)


class GenerationParams(BaseModel):
    schema_id: UUID
    scenario: Scenario = Scenario.SINGLE_MONTH
    start_date: date = Field(default_factory=lambda: date(2025, 1, 1))
    months: int = Field(default=1, ge=1, le=24, description="Number of months for multi_month scenario")
    transactions_per_month: TransactionRange = Field(default_factory=TransactionRange)
    opening_balance: str = Field(default="5000.00", description="Opening balance as string (decimal)")
    include_edge_cases: bool = Field(default=False, description="Include very long descriptions, round amounts, etc.")
    seed: int | None = Field(default=None, description="Random seed for reproducible output")
    currencies: list[str] = Field(default_factory=lambda: ["USD"], description="For international scenario")
    type_distribution: TypeDistribution = Field(default_factory=TypeDistribution)


class GenerationRequest(BaseModel):
    """Single PDF generation request."""
    params: GenerationParams


class BatchGenerationRequest(BaseModel):
    """Batch generation: multiple scenarios from the same schema."""
    schema_id: UUID
    scenarios: list[Scenario]
    start_date: date = Field(default_factory=lambda: date(2025, 1, 1))
    seed: int | None = None


class PreviewRequest(BaseModel):
    """Generate a first-page preview as PNG."""
    params: GenerationParams


class GenerationLogEntry(BaseModel):
    id: UUID
    schema_id: UUID
    scenario: Scenario
    parameters: GenerationParams
    file_count: int
    created_at: str
