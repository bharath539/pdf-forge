"""Pydantic models for V2 template-based PDF generation.

Instead of abstracting a format schema, V2 stores a complete template
of every visual element in the PDF, with data fields replaced by typed
placeholders. This produces pixel-perfect synthetic PDFs.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ElementCategory(str, Enum):
    """Whether a text element is structural (kept as-is) or data (replaced)."""
    STRUCTURAL = "structural"
    DATA_PLACEHOLDER = "data_placeholder"


class DataType(str, Enum):
    """The kind of data a placeholder represents."""
    AMOUNT = "amount"
    DATE = "date"
    NAME = "name"
    ADDRESS = "address"
    ACCOUNT_NUMBER = "account_number"
    DESCRIPTION = "description"
    PHONE = "phone"
    EMAIL = "email"
    REFERENCE = "reference"


class AccountType(str, Enum):
    CHECKING = "checking"
    SAVINGS = "savings"
    CREDIT_CARD = "credit_card"
    INVESTMENT = "investment"
    LOAN = "loan"


# ---------------------------------------------------------------------------
# Element models — each represents one visual element extracted from the PDF
# ---------------------------------------------------------------------------

class TextElement(BaseModel):
    """A single text item (word or phrase) from the PDF."""
    page: int = Field(description="0-indexed page number")
    x: float = Field(description="X position in points")
    y: float = Field(description="Y position in points (pdfplumber top-down)")
    text: str = Field(description="Original text or placeholder like '{amount}'")
    font_family: str = Field(default="Helvetica")
    font_size: float = Field(default=10.0)
    font_weight: str = Field(default="normal")
    color: str = Field(default="#000000")
    element_type: ElementCategory = Field(default=ElementCategory.STRUCTURAL)
    data_type: Optional[DataType] = Field(default=None)
    # For transaction row elements, which row they belong to
    row_index: Optional[int] = Field(default=None, description="Transaction row index (0-based)")
    # Width of the original text for fitting replacement values
    width: Optional[float] = Field(default=None, description="Width of original text in points")


class LineElement(BaseModel):
    """A drawn line (rule, border, separator)."""
    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    stroke_color: str = Field(default="#000000")
    stroke_width: float = Field(default=0.5)


class RectElement(BaseModel):
    """A drawn rectangle (background fill, box, border)."""
    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    fill_color: Optional[str] = Field(default=None)
    stroke_color: Optional[str] = Field(default=None)
    stroke_width: float = Field(default=0.0)


class ImageElement(BaseModel):
    """An image/logo area — stores bounding box only, not image data."""
    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    placeholder: bool = Field(default=True, description="If True, render as gray placeholder box")


# ---------------------------------------------------------------------------
# Page layout
# ---------------------------------------------------------------------------

class PageDimensions(BaseModel):
    """Dimensions for a single page."""
    width: float
    height: float


# ---------------------------------------------------------------------------
# Data field summary — counts of each data type for the faker
# ---------------------------------------------------------------------------

class DataFieldSummary(BaseModel):
    """Counts of each data type found in the template."""
    amounts: int = 0
    dates: int = 0
    names: int = 0
    addresses: int = 0
    account_numbers: int = 0
    descriptions: int = 0
    phones: int = 0
    emails: int = 0
    references: int = 0
    transaction_rows: int = 0


# ---------------------------------------------------------------------------
# Full PDF template
# ---------------------------------------------------------------------------

class PDFTemplate(BaseModel):
    """Complete template representing every visual element in a PDF.

    Structural elements have their original text preserved.
    Data elements have typed placeholders instead of PII.
    """
    version: str = Field(default="2.0")
    bank_name: str
    account_type: AccountType
    display_name: str
    page_dimensions: list[PageDimensions] = Field(description="Dimensions per page")
    text_elements: list[TextElement] = Field(default_factory=list)
    line_elements: list[LineElement] = Field(default_factory=list)
    rect_elements: list[RectElement] = Field(default_factory=list)
    image_elements: list[ImageElement] = Field(default_factory=list)
    page_count: int = Field(default=1)
    data_field_summary: DataFieldSummary = Field(default_factory=DataFieldSummary)
    # Row spacing info for transaction expansion/contraction
    transaction_row_height: Optional[float] = Field(
        default=None, description="Y-spacing between consecutive transaction rows"
    )
    transaction_area_start_y: Optional[float] = Field(
        default=None, description="Y position where transaction rows begin (page 0)"
    )
    transaction_area_page: int = Field(
        default=0, description="Page index where transaction table starts"
    )


# ---------------------------------------------------------------------------
# API / DB models
# ---------------------------------------------------------------------------

class PDFTemplateRecord(BaseModel):
    """Database record for a stored template."""
    id: UUID
    bank_name: str
    account_type: AccountType
    display_name: str
    template_json: PDFTemplate
    page_count: int
    data_field_count: int
    created_at: datetime
    updated_at: datetime


class PDFTemplateListItem(BaseModel):
    """List view of a template (without the full JSON)."""
    id: UUID
    bank_name: str
    account_type: AccountType
    display_name: str
    page_count: int
    data_field_count: int
    created_at: datetime
