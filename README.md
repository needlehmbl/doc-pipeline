# Local Document Intelligence Pipeline

[![CI](https://github.com/Needleeeeeeee/doc-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/Needleeeeeeee/doc-pipeline/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](#prerequisites)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A **fully local, no-paid-API** pipeline that turns messy documents (PDFs,
scanned images, CSVs) into clean, validated database records. A locally-hosted
LLM (via [Ollama](https://ollama.com)) does the structuring; a schema +
confidence validator refuses to blindly trust it; anything the model is unsure
about lands in a human review queue instead of silently polluting your data.

No data ever leaves your machine.

---

## Features

- **100% local & offline** — no API costs, no rate limits, no data exfiltration
- **Multi-format ingest** — text-layer PDFs, scanned PDFs (OCR fallback),
  images, and CSVs
- **LLM structuring** — prompts a local Ollama model for strict JSON,
  with automatic markdown-fence stripping and retry-on-garbage
- **Schema-driven validation** — the LLM prompt and the validator both read
  from a single schema, they can never drift apart
- **Per-field confidence** — every extracted field carries a 0–1 confidence
  score; low-confidence records go to a **review queue**, not the database
- **Confidence re-check** — when the *only* problem is a timid model, the
  flagged fields are re-prompted against the source text before escalating
  to a human (disable with `ENABLE_RECHECK=false`)
- **Cross-field consistency checks** — e.g. `sum(line_items) ≈ total_amount`
  catches transcription errors the model doesn't notice
- **Multi-row CSV support** — each row becomes its own record; a bad row
  doesn't sink the whole file
- **SQLite sink** — schema generated directly from the extraction schema;
  drop-in replaceable with Postgres
- **Dark web GUI** — React + TypeScript dashboard (see [Web GUI](#web-gui))
  with stats, records browser, human review queue (approve/reject with
  editing), drag-and-drop uploads, and inbox processing

## How it works

```
data/inbox/  →  ingest  →  extract (text/OCR)  →  structure (Ollama, strict JSON)
                                                           │
                                                           ▼
                                 reason file →  validate (schema + confidence +
                                                cross-field checks)
                                  │                             │
                             passes all                   flagged for review
                                  │                             │
                                  ▼                             ▼
                         load → db/pipeline.db       data/failed/review/*.record.json
                                  │
                                  ▼
                    data/processed/  (original file archived)
```

| Stage      | Module                      | Responsibility                               |
|------------|-----------------------------|----------------------------------------------|
| Ingest     | `ingest/watch.py`           | Find new files in `data/inbox/`, archive them|
| Extract    | `extract/extractor.py`      | Raw text from PDF/image/CSV (OCR fallback)   |
| Structure  | `extract/llm_structure.py`  | Prompt Ollama, parse + repair strict JSON    |
| Validate   | `validate/schema.py`        | Required fields, types, confidence, checks   |
| Load       | `load/db.py`                | Write validated records to SQLite            |
| Orchestrate| `scripts/run_pipeline.py`   | Wire everything together (CLI entry point)   |

### Routing: loaded vs review vs failed

Every document ends up in exactly one place:

- **`loaded`** — passed all validation; written to SQLite; file archived in `data/processed/`.
- **`review`** — schema-valid but the model was **not confident** on one or more
  fields, or a **cross-field check** failed. The extracted record is saved to
  `data/failed/review/*.record.json` with a `.reason.json` explaining why, and
  the original file is kept in `data/failed/`. A human inspects and decides.
- **`failed`** — something genuinely broke (unreadable file, empty text,
  invalid LLM output, DB error). Reason written to `data/failed/*.reason.json`.

The philosophy: an LLM's low confidence is information, not a failure — route
it to a human instead of trusting it or dropping it silently.

## Prerequisites

- **Python 3.10+**
- **[Ollama](https://ollama.com)** installed and running (`ollama serve`)
- A model pulled, e.g. `ollama pull llama3.2:3b`
- **tesseract-ocr** for scanned documents / images (text PDFs don't need it)

```bash
# Arch Linux
sudo pacman -S tesseract tesseract-data-eng
# Debian / Ubuntu
sudo apt install tesseract-ocr tesseract-ocr-eng
```

## Installation

```bash
git clone https://github.com/Needleeeeeeee/doc-pipeline.git
cd doc-pipeline

python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # defaults are fine to start
ollama pull llama3.2:3b       # first run only
```

Or with `make`:

```bash
make setup   # venv + deps + .env
make sample  # generate sample docs into data/inbox/
```

## Quick start

```bash
# Drop some sample documents into the inbox (generates a text PDF, a
# scanned PDF that needs OCR, and a 2-row expenses CSV):
python examples/generate_sample_docs.py

# Run the whole inbox through the pipeline:
python scripts/run_pipeline.py

# Inspect what made it into the database:
python scripts/run_pipeline.py --list

# Review anything the model was unsure about:
python scripts/run_pipeline.py --review
```

Processing a single file:

```bash
python scripts/run_pipeline.py --file data/inbox/invoice_001.pdf
```

Trusting schema-valid records even when the model is unsure (e.g. trustworthy
sources, demos):

```bash
python scripts/run_pipeline.py --lenient
```

> **Note:** small local models are honest about uncertainty — it's normal for
> some records to land in the review queue. That's the pipeline working as
> designed, not failing.

## Web GUI

A dark-themed React + TypeScript dashboard backed by a small FastAPI server,
so you can drive the whole pipeline without touching the CLI.

```bash
./gui.sh          # start backend (:8001) + frontend (:5174)
./gui.sh stop     # stop both
./gui.sh status   # check whether each server is up
```

Then open **http://localhost:5174**. The first run auto-installs any missing
deps (pip `fastapi`/`uvicorn`/`python-multipart`, plus `npm install`).

What you get:

| Tab      | What it does                                                        |
|----------|---------------------------------------------------------------------|
| Overview | Loaded / review / failed / inbox counts, total amount, failed files |
| Records  | Searchable table of every row in SQLite, with delete               |
| Review   | Low-confidence extractions with reasons — edit fields inline, then **approve → DB** or **reject** |
| Inbox    | Drag-and-drop uploads (PDF/PNG/JPG/CSV) plus per-file or whole-inbox processing, with optional lenient mode |
| Schema   | Live view of the extraction fields and cross-field checks          |

Prefer running the pieces manually?

```bash
uvicorn api.server:app --reload --port 8001  # backend (docs at /docs)
cd gui && npm install && npm run dev          # frontend (:5174)
```

## Project layout

```
doc-pipeline/
├── scripts/
│   └── run_pipeline.py      # CLI entry point
├── api/
│   └── server.py            # FastAPI backend for the web GUI
├── gui/                     # React + TypeScript frontend (dark theme)
│   └── src/App.tsx
├── gui.sh                   # one command to start/stop the GUI stack
├── ingest/
│   └── watch.py             # inbox scan + file archiving
├── extract/
│   ├── extractor.py         # PDF/image/CSV text + OCR
│   ├── llm_structure.py     # prompt builder + Ollama client
│   └── schema_config.py     # ★ single source of truth for fields & checks
├── validate/
│   └── schema.py            # schema, type, confidence, cross-field checks
├── load/
│   └── db.py                # SQLite (table generated from the schema)
├── examples/
│   └── generate_sample_docs.py
├── tests/                   # pytest suite (no LLM required to run)
├── data/inbox/              # drop documents here
├── data/processed/          # archived successes
├── data/failed/             # archive + .reason.json + review/ records
├── db/pipeline.db           # SQLite (auto-created)
└── .env                     # your local config
```

## Customizing the extraction schema

Everything you want extracted lives in `extract/schema_config.py`. Add a field
once and it automatically flows into the LLM prompt **and** the validator,
and a column gets added to SQLite:

```python
FieldSpec("vendor_name", "string", required=True,
          description="The company or person being paid"),
FieldSpec("total_amount", "number", required=True,
          description="Final total amount due, numeric only, no currency symbol"),
```

Cross-field consistency rules are declared the same way — here's one that
flags any invoice whose stated total disagrees with its own line items:

```python
CROSS_FIELD_CHECKS = [
    CheckSpec(
        name="line_items_sum_matches_total",
        description="sum of line_items.amount should equal total_amount",
        required_fields=["total_amount", "line_items"],
        validate=_line_items_sum_matches_total,
    ),
]
```

## Configuration (`.env`)

| Variable               | Default              | Description                                             |
|------------------------|----------------------|---------------------------------------------------------|
| `OLLAMA_MODEL`         | `llama3.2:3b`        | Ollama chat model used for structuring                  |
| `OLLAMA_HOST`          | `http://localhost:11434` | Ollama server address                                |
| `DB_PATH`              | `db/pipeline.db`     | SQLite database file                                    |
| `INBOX_DIR`            | `data/inbox`         | Drop folder for new documents                           |
| `PROCESSED_DIR`        | `data/processed`     | Archive for successful documents                        |
| `FAILED_DIR`           | `data/failed`        | Archive + `.reason.json` + `review/` for flagged output |
| `MIN_FIELD_CONFIDENCE` | `0.6`                | Below this a field's value routes the record to review  |
| `ENABLE_RECHECK`      | `true`               | Re-prompt the model once when only confidence is low    |
| `LOG_LEVEL`            | `INFO`               | `DEBUG` for maximal visibility                          |

## Testing

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

The test suite exercises the validator, extractor dispatch, file handling,
DB round-trips, and LLM response parsing — **no Ollama instance or network
needed**.

## Development

```bash
make test   # pytest
make lint   # ruff check (CI enforces this too)
```

## Why local-first?

Most "AI document processing" demos stop at calling OpenAI/Azure. This project
instead:

- Runs entirely on local hardware with a locally-hosted model
- Validates instead of blindly trusting LLM output
- Routes low-confidence extractions to a review queue instead of silent errors

That makes it cheap to run, private by default, and — most importantly — a
template for building trust into AI pipelines rather than hoping the model is
right.

## Roadmap

- [x] Simple FastAPI review UI (approve/reject records from the queue)
- [ ] Swappable Postgres sink to demonstrate schema migrations
- [ ] Batch progress bar + watch mode via `watchdog`
- [ ] Per-field confidence aggregation summary after each run

## License

[MIT](LICENSE)