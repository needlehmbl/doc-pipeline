import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from validate.schema import validate


def test_missing_required_field_fails():
    record = {
        "vendor_name": "Acme Corp",
        # invoice_date missing — required per schema_config.py
        "total_amount": 100.0,
        "_confidence": {"vendor_name": 0.95, "total_amount": 0.9},
    }
    result = validate(record)
    assert not result.passed
    assert any("invoice_date" in e for e in result.errors)


def test_low_confidence_routes_to_review():
    record = {
        "vendor_name": "Acme Corp",
        "invoice_date": "2026-01-01",
        "total_amount": 100.0,
        "_confidence": {
            "vendor_name": 0.95,
            "invoice_date": 0.95,
            "total_amount": 0.3,  # below MIN_FIELD_CONFIDENCE default of 0.6
        },
    }
    result = validate(record)
    assert not result.passed
    assert "total_amount" in result.low_confidence_fields


def test_valid_record_passes():
    record = {
        "vendor_name": "Acme Corp",
        "invoice_date": "2026-01-01",
        "total_amount": 100.0,
        "_confidence": {
            "vendor_name": 0.95,
            "invoice_date": 0.95,
            "total_amount": 0.9,
        },
    }
    result = validate(record)
    assert result.passed
    assert not result.errors
    assert not result.low_confidence_fields


def test_number_field_coerces_and_normalises():
    record = {
        "vendor_name": "Acme Corp",
        "invoice_date": "2026-01-01",
        "total_amount": "$1,299.50",  # string with symbols -> float
        "_confidence": {"vendor_name": 0.9, "invoice_date": 0.9, "total_amount": 0.9},
    }
    result = validate(record)
    assert result.passed
    assert record["total_amount"] == 1299.5


def test_bad_number_type_reports_error():
    record = {
        "vendor_name": "Acme Corp",
        "invoice_date": "2026-01-01",
        "total_amount": "not-a-number",
        "_confidence": {"vendor_name": 0.9, "invoice_date": 0.9, "total_amount": 0.9},
    }
    result = validate(record)
    assert not result.passed
    assert any("total_amount" in e for e in result.errors)


def test_date_coerced_to_iso_format():
    record = {
        "vendor_name": "Acme Corp",
        "invoice_date": "01/15/2026",
        "total_amount": 10.0,
        "_confidence": {"vendor_name": 0.9, "invoice_date": 0.9, "total_amount": 0.9},
    }
    result = validate(record)
    assert result.passed
    assert record["invoice_date"] == "2026-01-15"


def test_optionals_missing_are_not_penalised():
    record = {
        "vendor_name": "Acme",
        "invoice_date": "2026-01-01",
        "total_amount": 5.0,
        "_confidence": {"vendor_name": 0.9, "invoice_date": 0.9, "total_amount": 0.9},
    }
    result = validate(record)
    assert result.passed


def test_non_object_record_fails():
    result = validate("not-a-dict")
    assert not result.passed
    assert any("record" in e for e in result.errors)


def test_list_field_passes():
    record = {
        "vendor_name": "Acme",
        "invoice_date": "2026-01-01",
        "total_amount": 15.0,
        "line_items": [{"description": "widget", "amount": 15.0}],
        "_confidence": {
            "vendor_name": 0.9,
            "invoice_date": 0.9,
            "total_amount": 0.9,
            "line_items": 0.8,
        },
    }
    result = validate(record)
    assert result.passed


def test_list_confidence_as_array_uses_minimum():
    # Models sometimes return per-item confidence arrays for list fields.
    record = {
        "vendor_name": "Acme",
        "invoice_date": "2026-01-01",
        "total_amount": 15.0,
        "line_items": [{"description": "widget", "amount": 15.0}],
        "_confidence": {
            "vendor_name": 0.9,
            "invoice_date": 0.9,
            "total_amount": 0.9,
            "line_items": [0.9, 0.95],  # all above threshold -> ok
        },
    }
    assert validate(record).passed

    record["_confidence"]["line_items"] = [0.9, 0.4]  # weakest item flags it
    result = validate(record)
    assert not result.passed
    assert "line_items" in result.low_confidence_fields


def test_cross_field_sum_check_flags_mismatch():
    record = {
        "vendor_name": "Acme",
        "invoice_date": "2026-01-01",
        "total_amount": 100.0,  # line items only sum to 60
        "line_items": [
            {"description": "a", "amount": 40.0},
            {"description": "b", "amount": 20.0},
        ],
        "_confidence": {
            "vendor_name": 0.9,
            "invoice_date": 0.9,
            "total_amount": 0.9,
            "line_items": 0.9,
        },
    }
    result = validate(record)
    assert not result.passed
    assert any("line_items_sum_matches_total" in e for e in result.errors)