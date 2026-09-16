"""
Stage 4: Validate structured LLM output before it's allowed into the DB.

This is the layer that keeps the pipeline from blindly trusting the
model. Two independent checks, both must pass:

    1. Schema check — every required field (per EXTRACTION_SCHEMA) is
       present and non-null, and types roughly match (numbers parse
       as numbers, dates parse as dates, etc).
    2. Confidence check — every field's "_confidence" score meets
       MIN_FIELD_CONFIDENCE (from .env). A record can be schema-valid
       but still low-confidence, and should still go to review.

TODO(implementation):
    - ValidationResult dataclass: passed: bool, errors: list[str],
      low_confidence_fields: list[str]
    - validate(record: dict) -> ValidationResult
        - loop EXTRACTION_SCHEMA, check required fields present/non-null
        - attempt light type coercion (e.g. str(total_amount) -> float)
          and record a schema error if coercion fails
        - loop record["_confidence"], compare against MIN_FIELD_CONFIDENCE
    - is_valid(result) convenience bool helper used by run_pipeline.py
      to decide DB vs review-queue routing
"""

import datetime as _dt
import os
from dataclasses import dataclass, field

from extract.schema_config import CROSS_FIELD_CHECKS, EXTRACTION_SCHEMA

DEFAULT_MIN_CONFIDENCE = 0.6


@dataclass
class ValidationResult:
    passed: bool
    errors: list[str] = field(default_factory=list)
    low_confidence_fields: list[str] = field(default_factory=list)


def _coerce(value, type_name: str) -> tuple[bool, object]:
    """
    Light type check for a single field value. Returns (ok, coerced),
    where coerced is the cleaned value when `ok` is True so the loader
    can use normalised values (e.g. float, list) downstream.
    """
    if type_name == "string":
        if isinstance(value, str):
            return True, value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return True, str(value)
        return False, value

    if type_name == "number":
        if isinstance(value, bool):
            return False, value
        if isinstance(value, (int, float)):
            return True, float(value)
        if isinstance(value, str):
            try:
                return True, float(value.strip().replace(",", "").replace("$", ""))
            except ValueError:
                return False, value
        return False, value

    if type_name == "date":
        if isinstance(value, str):
            for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y", "%b %d, %Y", "%B %d, %Y"):
                try:
                    # Parsing day-granularity dates; timezone is not relevant here.
                    return True, _dt.datetime.strptime(value.strip(), fmt).strftime("%Y-%m-%d")  # noqa: DTZ007
                except ValueError:
                    continue
            # Last resort: dateutil-style ISO parse only for YYYY-MM-DD.
            try:
                return True, _dt.date.fromisoformat(value.strip()).isoformat()
            except ValueError:
                return False, value
        if isinstance(value, _dt.datetime):
            return True, value.date().isoformat()
        if isinstance(value, _dt.date):
            return True, value.isoformat()
        return False, value

    if type_name == "list":
        if isinstance(value, list):
            return True, value
        if isinstance(value, str):
            try:
                import json

                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return True, parsed
            except (ValueError, json.JSONDecodeError):
                pass
            return False, value
        return False, value

    return True, value


def _confidence_score(score) -> float:
    """
    Normalise a field's confidence to a single 0-1 float.

    Local models sometimes answer list-typed fields (e.g. line_items)
    with a list of per-item confidence scores; the field is only as
    trustworthy as its weakest item, so we take the minimum.
    """
    if isinstance(score, (list, tuple)):
        values = [_confidence_score(x) for x in score]
        return min(values) if values else 0.0
    try:
        value = float(score)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, value))


def validate(record: dict) -> ValidationResult:
    errors: list[str] = []
    low_confidence: list[str] = []

    min_confidence = float(os.getenv("MIN_FIELD_CONFIDENCE", DEFAULT_MIN_CONFIDENCE))

    if not isinstance(record, dict):
        return ValidationResult(passed=False, errors=["record is not an object"])

    confidence_scores = record.get("_confidence", {})
    if not isinstance(confidence_scores, dict):
        confidence_scores = {}
        errors.append("_confidence is not an object")

    for spec in EXTRACTION_SCHEMA:
        value = record.get(spec.name)

        if spec.required and (value is None or value == ""):
            errors.append(f"missing required field: {spec.name}")
            continue

        # Optional fields that simply weren't found shouldn't be
        # penalized for confidence — there's nothing to be confident
        # (or unconfident) about.
        if value is None or value == "":
            continue

        ok, coerced = _coerce(value, spec.type)
        if not ok:
            errors.append(
                f"field '{spec.name}' has invalid type: expected {spec.type}, got '{value!r}'"
            )
        else:
            # Normalise in place so the loader persists cleaned values.
            record[spec.name] = coerced

        score = _confidence_score(confidence_scores.get(spec.name, 0.0))
        if score < min_confidence:
            low_confidence.append(spec.name)

    for check in CROSS_FIELD_CHECKS:
        missing = [
            f for f in check.required_fields
            if record.get(f) is None or record.get(f) == ""
        ]
        if missing:
            continue  # nothing to cross-check reliably
        try:
            ok = check.validate(record)
        except Exception:  # a broken rule must not crash the run
            ok = False
        if not ok:
            errors.append(f"check failed ({check.name}): {check.description}")

    passed = not errors and not low_confidence
    return ValidationResult(passed=passed, errors=errors, low_confidence_fields=low_confidence)


def is_valid(result: ValidationResult) -> bool:
    return result.passed
