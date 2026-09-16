import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extract.llm_structure import build_prompt, build_recheck_prompt, parse_response


def test_build_prompt_contains_schema_fields():
    prompt = build_prompt("some raw text")
    assert "vendor_name" in prompt
    assert "total_amount" in prompt
    assert "some raw text" in prompt


def test_parse_response_plain_json():
    data = parse_response('{"vendor_name": "Acme"}')
    assert data == {"vendor_name": "Acme"}


def test_parse_response_strips_fence():
    data = parse_response('```json\n{"vendor_name": "Acme"}\n```')
    assert data == {"vendor_name": "Acme"}


def test_parse_response_strips_prose():
    data = parse_response(
        'Here is the result:\n{"vendor_name": "Acme", "total": 5}\nHope that helps.'
    )
    assert data["vendor_name"] == "Acme"


def test_recheck_prompt_quotes_only_flagged_fields():
    prompt = build_recheck_prompt(
        "doc text",
        {"vendor_name": "Acme", "total_amount": 5.0, "_confidence": {}},
        ["total_amount"],
    )
    assert "total_amount" in prompt
    assert "LOW confidence" in prompt
    assert '"vendor_name": "Acme"' in prompt