"""
Single source of truth for the fields this pipeline extracts.

Both `llm_structure.py` (prompt builder) and `validate/schema.py`
(validator) import from here, so the two can never drift apart —
add a field once and it's enforced everywhere.

Customize this for whatever document type you're demoing:
invoices, contracts, resumes, receipts, etc.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

FieldType = Literal["string", "number", "date", "list"]


@dataclass
class FieldSpec:
    name: str
    type: FieldType
    required: bool
    description: str  # used verbatim in the LLM prompt


@dataclass
class CheckSpec:
    """A cross-field consistency rule applied during validation.

    `required_fields` names the fields that must all be present (and
    non-null after initial validation) for the check to run. The callable
    receives the full record and returns True when the record is consistent.
    """

    name: str
    description: str  # used in the review reason when the check fails
    required_fields: list[str]
    validate: Callable[[dict], bool]


# --- Example schema: vendor invoices. Swap this out for your own doc type. ---
EXTRACTION_SCHEMA: list[FieldSpec] = [
    FieldSpec("vendor_name", "string", required=True,
              description="The company or person being paid"),
    FieldSpec("invoice_date", "date", required=True,
              description="Date the invoice was issued, format YYYY-MM-DD"),
    FieldSpec("invoice_number", "string", required=False,
              description="Invoice or reference number, if present"),
    FieldSpec("total_amount", "number", required=True,
              description="Final total amount due, numeric only, no currency symbol"),
    FieldSpec("currency", "string", required=False,
              description="Currency code, e.g. USD, PHP, EUR"),
    FieldSpec("line_items", "list", required=False,
              description="List of {description, amount} objects for each line item"),
]


def _line_items_sum_matches_total(record: dict) -> bool:
    items = record.get("line_items") or []
    if not isinstance(items, list) or not items:
        return True  # nothing to cross-check against
    try:
        total = float(record["total_amount"])
        item_sum = sum(float(it["amount"]) for it in items if isinstance(it, dict))
    except (KeyError, TypeError, ValueError):
        return False
    # Tolerate small rounding differences between the model's line items
    # and its stated total (OCR/rounding will occasionally differ by cents).
    return abs(item_sum - total) <= 0.5


CROSS_FIELD_CHECKS: list[CheckSpec] = [
    CheckSpec(
        name="line_items_sum_matches_total",
        description="sum of line_items.amount should equal total_amount",
        required_fields=["total_amount", "line_items"],
        validate=_line_items_sum_matches_total,
    ),
]


def schema_field_names(required_only: bool = False) -> list[str]:
    if required_only:
        return [f.name for f in EXTRACTION_SCHEMA if f.required]
    return [f.name for f in EXTRACTION_SCHEMA]
