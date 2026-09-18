#!/usr/bin/env python3
"""FastAPI backend for the doc-pipeline dark web GUI.

Run with:
    uvicorn api.server:app --reload --port 8001
"""

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Annotated, Any

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent

INBOX_DIR = os.getenv("INBOX_DIR", "data/inbox")
PROCESSED_DIR = os.getenv("PROCESSED_DIR", "data/processed")
FAILED_DIR = os.getenv("FAILED_DIR", "data/failed")
DB_PATH = os.getenv("DB_PATH", "db/pipeline.db")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")


def _resolve(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else ROOT / path


INBOX = _resolve(INBOX_DIR)
PROCESSED = _resolve(PROCESSED_DIR)
FAILED = _resolve(FAILED_DIR)
REVIEW_DIR = FAILED / "review"

# Local imports (need repo root on sys.path when run as module)
sys.path.insert(0, str(ROOT))

from extract.extractor import SUPPORTED_EXTENSIONS  # noqa: E402
from extract.schema_config import CROSS_FIELD_CHECKS, EXTRACTION_SCHEMA  # noqa: E402
from ingest.watch import list_pending  # noqa: E402
from load.db import fetch_all, init_db, insert_record  # noqa: E402

app = FastAPI(title="doc-pipeline API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5174", "http://127.0.0.1:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ApprovePayload(BaseModel):
    record: dict[str, Any] | None = None


class RejectPayload(BaseModel):
    reason: str | None = None


def _parse_db_row(row: dict) -> dict:
    row = dict(row)
    li = row.get("line_items")
    if isinstance(li, str):
        try:
            row["line_items"] = json.loads(li)
        except (ValueError, json.JSONDecodeError):
            pass
    return row


def _review_items() -> list[dict]:
    items: list[dict] = []
    if REVIEW_DIR.is_dir():
        for rec_path in sorted(REVIEW_DIR.glob("*.record.json")):
            try:
                rec = json.loads(rec_path.read_text())
            except json.JSONDecodeError:
                continue
            reason = rec.pop("_reason", "")
            items.append(
                {
                    "id": rec_path.stem.replace(".record", ""),
                    "file": rec_path.name,
                    "record": rec,
                    "reason": reason,
                }
            )
    return items


def _failed_reasons() -> list[dict]:
    out: list[dict] = []
    if FAILED.is_dir():
        for rp in sorted(FAILED.glob("*.reason.json")):
            try:
                data = json.loads(rp.read_text())
            except json.JSONDecodeError:
                continue
            out.append({"file": rp.name, **data})
    return out


@app.on_event("startup")
def _startup() -> None:
    init_db(str(ROOT / DB_PATH) if not Path(DB_PATH).is_absolute() else DB_PATH)


def _db() -> str:
    return str(ROOT / DB_PATH) if not Path(DB_PATH).is_absolute() else DB_PATH


@app.get("/api/health")
def health() -> dict:
    try:
        from extract.llm_structure import list_models, resolved_model

        available = list_models()
        model = resolved_model()
        ollama_ok = model in available
    except Exception as exc:  # Ollama down -> report, don't 500
        return {
            "ok": True,
            "ollama_reachable": False,
            "ollama_error": str(exc),
            "model": OLLAMA_MODEL,
        }
    return {
        "ok": True,
        "ollama_reachable": True,
        "model": model,
        "models": sorted(available),
        "ollama_ok": ollama_ok,
    }


@app.get("/api/stats")
def stats() -> dict:
    init_db(_db())
    records = fetch_all(_db())
    total_amount = 0.0
    for r in records:
        try:
            total_amount += float(r.get("total_amount") or 0)
        except (TypeError, ValueError):
            continue
    return {
        "loaded": len(records),
        "review": len(_review_items()),
        "failed": len(_failed_reasons()),
        "inbox": len(list_pending(str(ROOT / INBOX_DIR))),
        "total_amount": round(total_amount, 2),
    }


@app.get("/api/records")
def records() -> list[dict]:
    init_db(_db())
    return [_parse_db_row(r) for r in fetch_all(_db())]


@app.delete("/api/records/{record_id}")
def delete_record(record_id: int) -> dict:
    import sqlite3

    init_db(_db())
    with sqlite3.connect(_db()) as conn:
        cur = conn.execute("DELETE FROM extractions WHERE id = ?", (record_id,))
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Record not found")
    return {"ok": True, "deleted": record_id}


@app.get("/api/review")
def review_list() -> dict:
    return {"review": _review_items(), "failed": _failed_reasons()}


@app.post("/api/review/{item_id}/approve")
def review_approve(item_id: str, payload: ApprovePayload) -> dict:
    rec_path = REVIEW_DIR / f"{item_id}.record.json"
    # stem handling: files are "<label>.record.json", label may contain dots
    if not rec_path.exists():
        matches = list(REVIEW_DIR.glob(f"{item_id}*.record.json"))
        if not matches:
            raise HTTPException(status_code=404, detail="Review item not found")
        rec_path = matches[0]
    try:
        stored = json.loads(rec_path.read_text())
    except json.JSONDecodeError as err:
        raise HTTPException(status_code=500, detail="Corrupt review record") from err
    stored.pop("_reason", None)
    record = payload.record if payload.record is not None else stored
    source_file = record.get("source_file", rec_path.name)
    init_db(_db())
    try:
        insert_record(_db(), source_file, record)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"DB insert failed: {exc}") from exc
    rec_path.unlink(missing_ok=True)
    return {"ok": True, "approved": rec_path.name}


@app.post("/api/review/{item_id}/reject")
def review_reject(item_id: str) -> dict:
    rec_path = REVIEW_DIR / f"{item_id}.record.json"
    if not rec_path.exists():
        matches = list(REVIEW_DIR.glob(f"{item_id}*.record.json"))
        if not matches:
            raise HTTPException(status_code=404, detail="Review item not found")
        rec_path = matches[0]
    rec_path.unlink(missing_ok=True)
    return {"ok": True, "rejected": rec_path.name}


@app.get("/api/inbox")
def inbox() -> dict:
    pending = list_pending(str(ROOT / INBOX_DIR))
    return {
        "files": [
            {"name": p.name, "size": p.stat().st_size, "suffix": p.suffix.lower()}
            for p in pending
        ],
        "supported": sorted(SUPPORTED_EXTENSIONS),
    }


@app.post("/api/upload")
async def upload(files: Annotated[list[UploadFile], File(...)]) -> dict:
    INBOX.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    for f in files:
        suffix = Path(f.filename or "").suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {suffix} ({f.filename})",
            )
        dest = INBOX / Path(f.filename).name
        # dedupe
        if dest.exists():
            stem, sfx = dest.stem, dest.suffix
            i = 1
            while (INBOX / f"{stem}-{i}{sfx}").exists():
                i += 1
            dest = INBOX / f"{stem}-{i}{sfx}"
        with dest.open("wb") as out:
            shutil.copyfileobj(f.file, out)
        saved.append(dest.name)
    return {"ok": True, "saved": saved}


class ProcessPayload(BaseModel):
    file: str | None = None
    lenient: bool = False


@app.post("/api/process")
def process(payload: ProcessPayload) -> JSONResponse:
    # Lazy import so the API stays up even when Ollama is down.
    from scripts.run_pipeline import process_file

    init_db(_db())
    if payload.file:
        target = INBOX / Path(payload.file).name
        if not target.exists():
            raise HTTPException(status_code=404, detail="File not in inbox")
        status = process_file(target, lenient=payload.lenient)
        return JSONResponse({"results": [{target.name: status}]})
    pending = list_pending(str(ROOT / INBOX_DIR))
    if not pending:
        return JSONResponse({"results": [], "message": "Inbox is empty"})
    results = []
    for path in pending:
        try:
            status = process_file(path, lenient=payload.lenient)
        except Exception as exc:
            status = f"error: {exc}"
        results.append({path.name: status})
    return JSONResponse({"results": results})


@app.get("/api/schema")
def schema() -> dict:
    return {
        "fields": [
            {
                "name": f.name,
                "type": f.type,
                "required": f.required,
                "description": f.description,
            }
            for f in EXTRACTION_SCHEMA
        ],
        "checks": [
            {"name": c.name, "description": c.description} for c in CROSS_FIELD_CHECKS
        ],
    }


@app.get("/api/config")
def config() -> dict:
    return {
        "model": OLLAMA_MODEL,
        "ollama_host": OLLAMA_HOST,
        "db_path": DB_PATH,
        "min_confidence": os.getenv("MIN_FIELD_CONFIDENCE", "0.6"),
    }
