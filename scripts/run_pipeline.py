#!/usr/bin/env python3
"""
CLI entry point that wires together all pipeline stages:

    ingest -> extract -> structure (LLM) -> validate -> load

Usage:
    python scripts/run_pipeline.py                  # process everything in inbox
    python scripts/run_pipeline.py --file path.pdf  # process a single file
    python scripts/run_pipeline.py --review         # list flagged/failed records
    python scripts/run_pipeline.py --list           # show rows already in the DB
    python scripts/run_pipeline.py --lenient  # load schema-valid records despite low confidence
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Allow running as `python scripts/run_pipeline.py` from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from extract.extractor import extract_csv_rows, extract_text
from extract.llm_structure import recheck, structure
from ingest.watch import list_pending, move_to
from load.db import fetch_all, init_db, insert_record
from validate.schema import is_valid, validate

load_dotenv()

INBOX_DIR = os.getenv("INBOX_DIR", "data/inbox")
PROCESSED_DIR = os.getenv("PROCESSED_DIR", "data/processed")
FAILED_DIR = os.getenv("FAILED_DIR", "data/failed")
DB_PATH = os.getenv("DB_PATH", "db/pipeline.db")

# Recheck extraction once when the ONLY problem is low confidence, giving
# the model a chance to confirm or correct before routing to a human.
ENABLE_RECHECK = os.getenv("ENABLE_RECHECK", "true").lower() not in ("0", "false", "no")

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("pipeline")

STATUSES = ("loaded", "review", "failed")


def _write_reason(source_name: str, reason: str, dest_failed: Path) -> None:
    dest_failed.mkdir(parents=True, exist_ok=True)
    reason_path = dest_failed / f"{Path(source_name).stem}.reason.json"
    reason_path.write_text(
        json.dumps(
            {"source_file": source_name, "status": "flagged", "reason": reason},
            indent=2,
        )
    )


def _route_review(label: str, record: dict, reason: str) -> None:
    review_dir = Path(FAILED_DIR) / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    record = dict(record)
    record["_reason"] = reason
    (review_dir / f"{Path(label).stem}.record.json").write_text(
        json.dumps(record, indent=2)
    )


def _handle_chunk(chunk_text: str, label: str, source_file: str, lenient: bool = False) -> str:
    """
    Execute structure -> validate -> load for a single text chunk.
    Returns one of: "loaded", "review", "failed".
    """
    if not chunk_text.strip():
        raise ValueError("No text could be extracted for this record")

    logger.info("structuring %s with local LLM", label)
    record = structure(chunk_text)
    if not isinstance(record, dict):
        raise TypeError("LLM output is not a JSON object")

    result = validate(record)

    # When the only problem is low confidence, offer the model one focused
    # recheck against the source text before handing it to a human.
    if (
        ENABLE_RECHECK
        and not is_valid(result)
        and result.low_confidence_fields
        and not result.errors
    ):
        logger.info(
            "%s: low confidence on %s; requesting model recheck",
            label,
            ", ".join(result.low_confidence_fields),
        )
        try:
            rechecked = recheck(chunk_text, record, result.low_confidence_fields)
            recheck_result = validate(rechecked)
            if is_valid(recheck_result):
                record = rechecked
                result = recheck_result
        except Exception as exc:  # keep the original result if recheck fails
            logger.warning("%s: recheck failed (%s); keeping original", label, exc)

    if not is_valid(result):
        if lenient and not result.errors:
            # --lenient: trust schema-valid records even if the model was unsure.
            logger.info("%s -> loaded (lenient, ignoring low confidence)", label)
            insert_record(DB_PATH, source_file, record)
            return "loaded"

        reason_parts: list[str] = []
        if result.errors:
            reason_parts.append("validation: " + "; ".join(result.errors))
        if result.low_confidence_fields:
            reason_parts.append(
                f"low confidence: {', '.join(result.low_confidence_fields)}"
            )
        reason = " | ".join(reason_parts) or "flagged for review"
        _route_review(label, record, reason)
        logger.info("%s -> review queue (%s)", label, reason)
        return "review"

    insert_record(DB_PATH, source_file, record)
    logger.info("%s -> loaded", label)
    return "loaded"


def process_file(path: Path, lenient: bool = False) -> str:
    """
    Run a single file through extract -> structure -> validate -> load.
    For multi-row CSVs, each row is structured and loaded independently.

    Returns one of: "loaded", "review", "failed".
    """
    path = Path(path)
    try:
        if path.suffix.lower() == ".csv":
            chunks = extract_csv_rows(path)
            statuses = [
                _handle_chunk(chunk, f"{path.stem}-row{i}", path.name, lenient)
                for i, chunk in enumerate(chunks, start=1)
            ]
        else:
            raw_text = extract_text(path)
            statuses = [_handle_chunk(raw_text, path.stem, path.name, lenient)]
    except Exception as exc:  # anything raising here routes to data/failed/
        logger.error("%s failed: %s", path.name, exc)
        _write_reason(path.name, str(exc), Path(FAILED_DIR))
        move_to(path, FAILED_DIR)
        return "failed"

    agg = {s: statuses.count(s) for s in STATUSES}

    if agg["failed"] and not agg["loaded"] and not agg["review"]:
        move_to(path, FAILED_DIR)
        return "failed"

    if agg["review"] and not agg["loaded"]:
        notes = "; ".join(
            f"{n} {s}(s)" for n, s in agg.items() if s and n != "loaded"
        )
        _write_reason(path.name, notes + "; see review/ for details", Path(FAILED_DIR))
        move_to(path, FAILED_DIR)
        return "review"

    if agg["loaded"] and (agg["review"] or agg["failed"]):
        logger.warning(
            "%s partially loaded (%s); archiving processed file to review dir",
            path.name,
            agg,
        )
        _write_reason(path.name, f"partial: {agg}", Path(FAILED_DIR))
        move_to(path, FAILED_DIR)
        return "review"

    move_to(path, PROCESSED_DIR)
    return "loaded"


def review_mode() -> None:
    review_dir = Path(FAILED_DIR) / "review"
    reasons = sorted(Path(FAILED_DIR).glob("*.reason.json"))
    if not reasons and not (review_dir.is_dir() and any(review_dir.iterdir())):
        print("No flagged records under data/failed/. Nothing to review.")
        return

    for reason_path in reasons:
        try:
            data = json.loads(reason_path.read_text())
        except json.JSONDecodeError:
            continue
        print(f"\n[{reason_path.stem.replace('.reason', '')}]")
        print(f"  reason: {data.get('reason', 'n/a')}")

    records = sorted(review_dir.glob("*.record.json")) if review_dir.is_dir() else []
    if records:
        print(f"\n{len(records)} extracted record(s) awaiting review:")
        for rec_path in records:
            rec = json.loads(rec_path.read_text())
            reason = rec.pop("_reason", "")
            print(f"\n  {rec_path.stem}")
            for k, v in rec.items():
                print(f"    {k}: {v}")
            if reason:
                print(f"    _reason: {reason}")


def list_mode() -> None:
    rows = fetch_all(DB_PATH)
    if not rows:
        print("No records in the database yet.")
        return
    preferred = (
        "source_file",
        "vendor_name",
        "invoice_date",
        "invoice_number",
        "total_amount",
        "currency",
    )
    headers = ("id", *[k for k in preferred if k in rows[0]], "processed_at")
    widths = {
        h: max(len(h), *(len(str(r.get(h, ""))) for r in rows)) for h in headers
    }
    print("  ".join(h.ljust(widths[h]) for h in headers))
    print("  ".join("-" * widths[h] for h in headers))
    for r in rows:
        print("  ".join(str(r.get(h, "")).ljust(widths[h]) for h in headers))


def main() -> None:
    parser = argparse.ArgumentParser(description="Local document intelligence pipeline")
    parser.add_argument(
        "--file", type=str, help="Process a single file instead of the whole inbox"
    )
    parser.add_argument(
        "--review", action="store_true", help="List flagged/failed records for manual review"
    )
    parser.add_argument(
        "--list", action="store_true", help="Show records already loaded into the database"
    )
    parser.add_argument(
        "--lenient",
        action="store_true",
        help="Load records that pass schema checks even when the model reports low confidence",
    )
    args = parser.parse_args()

    init_db(DB_PATH)

    if args.review:
        review_mode()
        return

    if args.list:
        list_mode()
        return

    if args.file:
        status = process_file(Path(args.file), lenient=args.lenient)
        print(f"{args.file}: {status}")
        return

    pending = list_pending(INBOX_DIR)
    if not pending:
        print("No pending files in inbox. Drop files into data/inbox/ and re-run.")
        return

    counts = {s: 0 for s in STATUSES}
    for path in pending:
        status = process_file(path, lenient=args.lenient)
        counts[status] += 1
        print(f"{path.name}: {status}")

    print(
        f"\nDone. loaded={counts['loaded']} review={counts['review']} failed={counts['failed']}"
    )


if __name__ == "__main__":
    main()