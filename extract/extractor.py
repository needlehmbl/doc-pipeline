"""
Stage 2: Extract raw text content from an input file.

Handles PDFs (text-layer first, OCR fallback for scanned pages),
plain images, and CSVs. Output is always a plain string of extracted
text that gets handed to `llm_structure.py` for structuring.

TODO(implementation):
    - extract_pdf: try PyMuPDF text extraction per page; if a page's
      extracted text is suspiciously short (< ~20 chars), rasterize
      that page and run pytesseract on it instead.
    - extract_image: straight pytesseract.image_to_string.
    - extract_csv: read with pandas, return a text rendering (e.g.
      df.to_string()) since the LLM structuring step works on text.
    - Add basic logging of which extraction path was used per file,
      useful later for debugging why a given document extracted poorly.
"""

import logging
from pathlib import Path

import pandas as pd
import pytesseract
from PIL import Image

try:
    import pymupdf as fitz  # PyMuPDF >= 1.24 recommended import
except ImportError:  # pragma: no cover - older PyMuPDF releases
    import fitz

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".csv"}

# Pages whose text layer yields fewer than this many characters are
# treated as scans and sent through OCR instead.
MIN_TEXT_PAGE_CHARS = 20


def extract_text(file_path: Path) -> str:
    """
    Dispatch to the right extractor based on file extension.

    Raises ValueError for unsupported file types so the caller can
    route the file to data/failed/ with a clear reason.
    """
    file_path = Path(file_path)
    if not file_path.is_file():
        raise FileNotFoundError(f"File does not exist: {file_path}")

    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        return extract_pdf(file_path)
    elif suffix in {".png", ".jpg", ".jpeg"}:
        return extract_image(file_path)
    elif suffix == ".csv":
        return extract_csv(file_path)
    else:
        raise ValueError(f"Unsupported file type: {suffix}")


def extract_pdf(file_path: Path) -> str:
    """
    Extract text from a PDF.

    Pages with a usable text layer are extracted directly with PyMuPDF;
    pages that look like scans (little/no extractable text) are rasterized
    and run through pytesseract OCR instead.
    """
    parts: list[str] = []
    doc = fitz.open(file_path)
    try:
        for page_num, page in enumerate(doc, start=1):
            text = page.get_text().strip()
            if len(text) >= MIN_TEXT_PAGE_CHARS:
                parts.append(text)
                logger.info("pdf: page %d extracted from text layer", page_num)
                continue

            # Likely a scan — rasterize and OCR.
            try:
                pix = page.get_pixmap(dpi=300)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                page_text = pytesseract.image_to_string(img)
            except pytesseract.TesseractNotFoundError as exc:
                logger.warning(
                    "pdf: page %d has no text layer and tesseract is missing; skipping OCR",
                    page_num,
                )
                if not text:
                    raise ValueError(
                        "Page has no text layer and tesseract is unavailable for OCR. "
                        "Install tesseract-ocr to process scanned PDFs."
                    ) from exc
                page_text = text

            if page_text.strip():
                parts.append(page_text)
                logger.info("pdf: page %d extracted via OCR", page_num)
            else:
                logger.warning("pdf: page %d yielded no text", page_num)
    finally:
        doc.close()

    return "\n\n".join(p for p in parts if p.strip())


def extract_image(file_path: Path) -> str:
    """Run OCR on a single image with pytesseract."""
    try:
        with Image.open(file_path) as img:
            text = pytesseract.image_to_string(img)
    except pytesseract.TesseractNotFoundError as exc:
        raise ValueError(
            "tesseract-ocr is not installed; cannot OCR images."
        ) from exc
    logger.info("image: OCR performed on %s (%d chars)", file_path.name, len(text))
    return text


def extract_csv(file_path: Path) -> str:
    """Read a CSV and render it as aligned text for the LLM step."""
    try:
        df = pd.read_csv(file_path)
    except Exception as exc:
        raise ValueError(f"Could not parse CSV: {exc}") from exc
    if df.empty:
        raise ValueError(f"CSV is empty: {file_path.name}")
    logger.info("csv: read %d rows x %d columns", len(df), len(df.columns))
    return df.to_string(index=False)


def extract_csv_rows(file_path: Path) -> list[str]:
    """
    Read a CSV and return one text chunk per data row (header + that row).

    Multi-row CSVs map naturally to multi-record output: each row becomes
    its own extraction/record, so a 50-row expense report yields 50
    structured entries instead of one mangled aggregate or data loss.
    """
    try:
        df = pd.read_csv(file_path)
    except Exception as exc:
        raise ValueError(f"Could not parse CSV: {exc}") from exc
    if df.empty:
        raise ValueError(f"CSV is empty: {file_path.name}")

    header = pd.DataFrame(columns=df.columns)
    chunks = []
    for _, row in df.iterrows():
        chunk = pd.concat([header, row.to_frame().T], ignore_index=True).to_string(index=False)
        chunks.append(chunk)
    logger.info("csv: split into %d rows", len(chunks))
    return chunks
