"""
Stage 5: Load validated records into SQLite.

Kept intentionally simple (raw sqlite3, no ORM) so the whole pipeline
stays dependency-light and easy to explain in a portfolio writeup.
Swapping this module for a Postgres-backed one later (using the same
function signatures) is a natural "v2" extension to mention.

TODO(implementation):
    - init_db(db_path): CREATE TABLE IF NOT EXISTS extractions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source_file TEXT NOT NULL,
          vendor_name TEXT,
          invoice_date TEXT,
          invoice_number TEXT,
          total_amount REAL,
          currency TEXT,
          line_items TEXT,          -- JSON-encoded
          processed_at TEXT NOT NULL
      )
      Column set should mirror EXTRACTION_SCHEMA field names — consider
      generating the CREATE TABLE statement from the schema directly so
      the two never drift, same pattern as extract/schema_config.py.
    - insert_record(db_path, source_file, record: dict): serialize
      list/dict fields (e.g. line_items) to JSON text before insert.
    - fetch_all(db_path) -> list[dict]: for a quick CLI/dashboard view.
"""

import datetime as _dt
import json
import sqlite3
from pathlib import Path

from extract.schema_config import EXTRACTION_SCHEMA, schema_field_names

# SQLite column type mapping for EXTRACTION_SCHEMA field types.
_TYPE_TO_SQL = {
    "string": "TEXT",
    "date": "TEXT",
    "number": "REAL",
    "list": "TEXT",  # JSON-encoded
}


def get_connection(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str) -> None:
    columns = [
        "id INTEGER PRIMARY KEY AUTOINCREMENT",
        "source_file TEXT NOT NULL",
        *[
            f"{spec.name} {_TYPE_TO_SQL.get(spec.type, 'TEXT')}"
            for spec in EXTRACTION_SCHEMA
        ],
        "processed_at TEXT NOT NULL",
    ]
    create_sql = "CREATE TABLE IF NOT EXISTS extractions (\n    " + ",\n    ".join(columns) + "\n)"
    with get_connection(db_path) as conn:
        conn.execute(create_sql)


def insert_record(db_path: str, source_file: str, record: dict) -> None:
    field_names = schema_field_names()
    values = []
    for name in field_names:
        value = record.get(name)
        if isinstance(value, (list, dict)):
            value = json.dumps(value)
        elif isinstance(value, bool):
            value = int(value)
        values.append(value)

    cols = ", ".join(field_names)
    placeholders = ", ".join("?" for _ in field_names)
    sql = (
        f"INSERT INTO extractions (source_file, {cols}, processed_at) "
        f"VALUES (?, {placeholders}, ?)"
    )
    with get_connection(db_path) as conn:
        conn.execute(
            sql,
            (
                source_file,
                *values,
                _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            ),
        )


def fetch_all(db_path: str) -> list[dict]:
    with get_connection(db_path) as conn:
        rows = conn.execute("SELECT * FROM extractions ORDER BY id").fetchall()
    return [dict(r) for r in rows]
