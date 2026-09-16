import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from load.db import fetch_all, get_connection, init_db, insert_record


def test_init_and_insert_and_fetch(tmp_path):
    db = str(tmp_path / "test.db")
    init_db(db)
    insert_record(
        db,
        "invoice_001.pdf",
        {
            "vendor_name": "Acme",
            "invoice_date": "2026-01-01",
            "invoice_number": "INV-1",
            "total_amount": 12.5,
            "currency": "USD",
            "line_items": [{"description": "widget", "amount": 12.5}],
        },
    )
    rows = fetch_all(db)
    assert len(rows) == 1
    row = rows[0]
    assert row["vendor_name"] == "Acme"
    assert row["total_amount"] == 12.5
    assert "widget" in row["line_items"]


def test_init_db_is_idempotent(tmp_path):
    db = str(tmp_path / "test.db")
    init_db(db)
    init_db(db)
    assert get_connection(db).execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='extractions'"
    ).fetchone()