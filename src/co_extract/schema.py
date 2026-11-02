"""Output schema for a change order.

Two layers:

* ``ChangeOrder`` / ``LineItem`` -- the clean, typed business object. This is
  what downstream systems consume once a document is accepted.
* ``FieldResult`` / ``ExtractionResult`` -- the envelope the pipeline emits:
  every field carries its value *plus* confidence, provenance and evidence so a
  reviewer (human or machine) can decide what to trust.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class Reason(str, Enum):
    OWNER_REQUEST = "owner_request"
    DESIGN_ERROR = "design_error"  # errors / omissions in drawings or specs
    UNFORESEEN_CONDITION = "unforeseen_condition"  # concealed / differing site conditions
    REGULATORY = "regulatory"  # code, inspector, permit requirements
    VALUE_ENGINEERING = "value_engineering"  # cost-reduction substitutions
    OTHER = "other"


class Status(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class LineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str
    quantity: Decimal | None = None
    unit: str | None = None
    unit_price: Decimal | None = None
    amount: Decimal

    @field_serializer("quantity", "unit_price", "amount")
    def _num(self, v: Decimal | None) -> float | None:
        """Serialize a Decimal as a float for JSON output."""
        return None if v is None else float(v)


class ChangeOrder(BaseModel):
    """Validated change order. Money is Decimal internally, float in JSON."""

    model_config = ConfigDict(extra="forbid")

    change_order_number: str
    project_name: str | None = None
    project_number: str | None = None
    owner: str | None = None
    contractor: str | None = None
    date_issued: date | None = None
    description: str | None = None
    reason: Reason | None = None
    status: Status | None = None
    line_items: list[LineItem] = Field(default_factory=list)
    subtotal: Decimal | None = None
    markup: Decimal | None = None  # overhead & profit, fees
    tax: Decimal | None = None
    total_change_amount: Decimal  # negative for a credit / deductive change
    original_contract_sum: Decimal | None = None
    prior_change_orders_total: Decimal | None = None
    contract_sum_before: Decimal | None = None
    new_contract_sum: Decimal | None = None
    schedule_impact_days: int | None = None  # negative = time reduction
    new_completion_date: date | None = None

    @field_serializer(
        "subtotal", "markup", "tax", "total_change_amount", "original_contract_sum",
        "prior_change_orders_total", "contract_sum_before", "new_contract_sum",
    )
    def _money(self, v: Decimal | None) -> float | None:
        """Serialize a money Decimal as a float for JSON output."""
        return None if v is None else float(v)


# Field name -> kind. Drives normalisation, grounding and validation.
SCALAR_FIELDS: dict[str, str] = {
    "change_order_number": "id",
    "project_name": "text",
    "project_number": "id",
    "owner": "text",
    "contractor": "text",
    "date_issued": "date",
    "description": "text",
    "reason": "enum",
    "status": "enum",
    "subtotal": "money",
    "markup": "money",
    "tax": "money",
    "total_change_amount": "money",
    "original_contract_sum": "money",
    "prior_change_orders_total": "money",
    "contract_sum_before": "money",
    "new_contract_sum": "money",
    "schedule_impact_days": "int",
    "new_completion_date": "date",
}
REQUIRED_FIELDS = ("change_order_number", "total_change_amount")
LINE_ITEM_FIELDS: dict[str, str] = {
    "description": "text",
    "quantity": "number",
    "unit": "text",
    "unit_price": "money",
    "amount": "money",
}


class FieldResult(BaseModel):
    value: Any = None
    confidence: float = 0.0
    sources: list[str] = Field(default_factory=list)  # "rules", "llm", "derived"
    evidence: str | None = None  # verbatim snippet from the document
    flags: list[str] = Field(default_factory=list)  # machine-readable issues
    reasons: list[str] = Field(default_factory=list)  # why this confidence


class LineItemResult(BaseModel):
    fields: dict[str, FieldResult]
    confidence: float  # min over required item fields
    evidence: str | None = None


class ValidationIssue(BaseModel):
    rule: str
    severity: str  # "error" | "warning"
    message: str
    fields: list[str] = Field(default_factory=list)


class ExtractionResult(BaseModel):
    document: str
    status: str  # "auto_accept" | "needs_review" | "failed"
    overall_confidence: float
    fields: dict[str, FieldResult]
    line_items: list[LineItemResult]
    validation: list[ValidationIssue]
    needs_review: list[str]
    change_order: dict[str, Any] | None = None  # the clean object, if it validates
    meta: dict[str, Any] = Field(default_factory=dict)
