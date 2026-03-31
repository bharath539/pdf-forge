"""Pydantic models for bank statement format schemas."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class AccountType(str, Enum):
    CHECKING = "checking"
    SAVINGS = "savings"
    CREDIT_CARD = "credit_card"
    INVESTMENT = "investment"
    LOAN = "loan"


class FontRole(str, Enum):
    HEADER = "header"
    SUBHEADER = "subheader"
    BODY = "body"
    FOOTER = "footer"
    TABLE_HEADER = "table_header"
    TABLE_BODY = "table_body"


class SectionType(str, Enum):
    HEADER = "header"
    ACCOUNT_SUMMARY = "account_summary"
    TRANSACTION_TABLE = "transaction_table"
    FOOTER = "footer"
    DISCLAIMER = "disclaimer"


class ElementType(str, Enum):
    LOGO_PLACEHOLDER = "logo_placeholder"
    TEXT_FIELD = "text_field"
    LINE_RULE = "line_rule"
    BACKGROUND_FILL = "background_fill"


# --- Page Layout ---

class PageLayout(BaseModel):
    width: float = Field(description="Page width in points")
    height: float = Field(description="Page height in points")
    margins: Margins


class Margins(BaseModel):
    top: float
    right: float
    bottom: float
    left: float


# --- Fonts ---

class FontSpec(BaseModel):
    role: FontRole
    family: str = Field(description="Font family name")
    size: float = Field(description="Font size in points")
    weight: str = Field(default="normal", description="normal, bold, light")
    color: str = Field(default="#000000", description="Hex color code")


# --- Section Elements ---

class BoundingBox(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float


class SectionElement(BaseModel):
    type: ElementType
    role: str | None = None
    bbox: BoundingBox | None = None
    font_ref: FontRole | None = None
    format: str | None = Field(default=None, description="Format pattern e.g. 'Page {n} of {total}'")


class SummaryField(BaseModel):
    role: str = Field(description="e.g. account_number_masked, opening_balance")
    label: str = Field(description="Display label")
    format: str = Field(description="Value format pattern")


class TableColumn(BaseModel):
    header: str = Field(description="Column header text")
    x_start: float
    x_end: float
    format: str = Field(description="Column data format: text, date, amount")
    max_chars: int | None = None
    alignment: str = Field(default="left", description="left, right, center")


class Section(BaseModel):
    type: SectionType
    y_start: float = Field(description="Section start Y position (negative = from page bottom)")
    y_end: float | None = None
    elements: list[SectionElement] | None = None
    fields: list[SummaryField] | None = None
    columns: list[TableColumn] | None = None
    row_height: float | None = None
    alternate_row_fill: str | None = Field(default=None, description="Hex color for alternating rows")
    header_underline: bool = False


# --- Description Patterns ---

class DescriptionPattern(BaseModel):
    category: str = Field(description="e.g. debit_card, ach, check, transfer, atm")
    pattern: str = Field(description="Pattern with placeholders: {merchant}, {city}, {state}, etc.")


# --- Page Break Rules ---

class PageBreakRules(BaseModel):
    min_rows_before_break: int = Field(default=3)
    continuation_header: bool = Field(default=True, description="Re-print column headers on new pages")
    orphan_control: bool = Field(default=True)


# --- Full Format Schema ---

class FormatSchema(BaseModel):
    schema_version: str = Field(default="1.0")
    bank_name: str
    account_type: AccountType
    display_name: str
    page: PageLayout
    fonts: list[FontSpec]
    sections: list[Section]
    page_break_rules: PageBreakRules = Field(default_factory=PageBreakRules)
    description_patterns: list[DescriptionPattern] = Field(default_factory=list)


# --- API Response Models ---

class FormatSchemaRecord(BaseModel):
    id: UUID
    bank_name: str
    account_type: AccountType
    display_name: str
    schema_json: FormatSchema
    page_count: int
    created_at: datetime
    updated_at: datetime


class FormatSchemaListItem(BaseModel):
    id: UUID
    bank_name: str
    account_type: AccountType
    display_name: str
    page_count: int
    created_at: datetime


class FormatSchemaCreate(BaseModel):
    bank_name: str
    account_type: AccountType
    display_name: str


class FormatSchemaUpdate(BaseModel):
    bank_name: str | None = None
    account_type: AccountType | None = None
    display_name: str | None = None
