"""
Stage 3: Prompt a local Ollama model to turn raw extracted text into
strict JSON matching EXTRACTION_SCHEMA.

Design notes for implementation:
    - Build the prompt dynamically from EXTRACTION_SCHEMA so schema
      changes propagate automatically (see schema_config.py).
    - Instruct the model to output ONLY JSON, no prose, no markdown
      fences — then still defensively strip fences before parsing,
      since local models don't always follow instructions perfectly.
    - Ask the model to also return a `_confidence` object mapping each
      field name to a 0-1 confidence score. This is what the validator
      uses to route low-confidence extractions to the review queue
      instead of silently trusting the model.
    - Wrap the ollama call + json.loads in try/except with at least
      one retry (e.g. re-prompt with "your last response was not valid
      JSON, return only JSON") before giving up and routing to failed.

TODO(implementation):
    - build_prompt(raw_text) -> str
    - call_ollama(prompt) -> str  (wraps ollama.chat or ollama.generate)
    - parse_response(raw_response) -> dict  (strip fences, json.loads,
      retry once on failure)
    - structure(raw_text) -> dict  (the public entry point that ties
      the above together and is called by scripts/run_pipeline.py)
"""

import json
import logging
import os

import ollama

from extract.schema_config import EXTRACTION_SCHEMA

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "llama3.1"
DEFAULT_HOST = "http://localhost:11434"

# Number of corrective re-prompts after the first response fails to
# parse as valid JSON before we give up.
MAX_RETRIES = 2


def build_prompt(raw_text: str) -> str:
    field_names = ", ".join(f'"{f.name}"' for f in EXTRACTION_SCHEMA)
    field_lines = "\n".join(
        f'  - "{f.name}" ({f.type}, {"required" if f.required else "optional"}): '
        f"{f.description}"
        for f in EXTRACTION_SCHEMA
    )
    return f"""You are a strict data extraction engine. Extract the following
fields from the document text below and return ONLY a JSON object —
no prose, no markdown code fences, nothing but valid JSON.

Fields to extract:
{field_lines}

Also include a "_confidence" object with a 0.0-1.0 confidence score for
EACH and EVERY field above — the key "_confidence" must contain exactly
these keys: {field_names}. Missing or null values should get a low score
(0.0-0.3). Use high scores (0.9+) only when the value appears directly in
the document.

If a field is not present in the document, use null and give it a low
confidence score rather than guessing.

Document text:
---
{raw_text}
---

JSON:"""


def build_recheck_prompt(raw_text: str, previous: dict, low_fields: list[str]) -> str:
    """
    Ask the model to re-examine a record where values passed schema checks
    but carried low confidence. The stated field names are quoted verbatim
    so the model can confirm or correct them against the source text.
    """
    quoted_items = [
        f'"{k}": {json.dumps(v, ensure_ascii=False)}'
        for k, v in previous.items()
        if k != "_confidence"
    ]
    quoted = ",\n    ".join(quoted_items)
    return f"""You previously extracted this record from a document:

{{
    {quoted}
}}

The following fields were marked with LOW confidence and need re-checking:
    {", ".join(low_fields)}

Re-examine the document text. For each low-confidence field, keep the
value ONLY if it is explicitly supported by the text; otherwise correct it.
Then return the FULL record as a single JSON object, including the
"_confidence" object with a 0.0-1.0 score for EVERY field. Set a score of
0.9 or higher only when the value is clearly and directly visible in the
text below. Be strict and honest.

Document text:
---
{raw_text}
---

JSON:"""


def call_ollama(prompt: str) -> str:
    model = os.getenv("OLLAMA_MODEL", DEFAULT_MODEL)
    client = ollama.Client(host=os.getenv("OLLAMA_HOST", DEFAULT_HOST))
    response = client.generate(model=model, prompt=prompt, options={"temperature": 0})

    # Newer ollama clients return a typed GenerateResponse model;
    # older ones returned a dict. Handle both.
    if isinstance(response, dict):
        text = response.get("response")
    else:
        text = getattr(response, "response", None)
    if not isinstance(text, str) or not text:
        raise RuntimeError(f"Unexpected ollama response: {response!r}")
    return text


def parse_response(raw_response: str) -> dict:
    cleaned = raw_response.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.removeprefix("json").removeprefix("JSON").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = _extract_json_object(cleaned)
        if match:
            return json.loads(match)
        raise


def _extract_json_object(text: str) -> str | None:
    """Pull out the first {...} block from text, ignoring prose around it."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    candidate = text[start : end + 1]
    try:
        json.loads(candidate)
        return candidate
    except json.JSONDecodeError:
        return None


def structure(raw_text: str) -> dict:
    """
    Public entry point: raw extracted text in, structured dict out
    (including a "_confidence" sub-dict). Raises on unrecoverable
    failure so the caller can route the file to data/failed/.
    """
    if not raw_text.strip():
        raise ValueError("Cannot structure empty text")

    prompt = build_prompt(raw_text)
    return _extract_with_retry(prompt)


def recheck(raw_text: str, previous: dict, low_fields: list[str]) -> dict:
    """
    Re-run extraction focused on fields the model flagged as low-confidence.

    Values already passed the schema/cross-field checks; this second pass
    asks the model to confirm or correct them against the source text, which
    filters out spurious low-confidence flags from small models. Still raises
    if the model stops producing valid JSON.
    """
    prompt = build_recheck_prompt(raw_text, previous, low_fields)
    return _extract_with_retry(prompt)


def _extract_with_retry(prompt: str) -> dict:
    errors: list[str] = []
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = call_ollama(prompt)
            return parse_response(response)
        except (json.JSONDecodeError, KeyError, IndexError, RuntimeError) as exc:
            errors.append(str(exc))
            logger.warning("llm_structure: attempt %d failed to parse JSON", attempt + 1)
            if attempt >= MAX_RETRIES:
                break
            prompt = (
                "Your previous response was not valid JSON. Return ONLY a single "
                "JSON object with no prose, no code fences.\n\n" + prompt
            )

    raise ValueError(
        f"LLM did not return valid JSON after {MAX_RETRIES + 1} attempts: "
        f"{errors[-1] if errors else 'unknown error'}"
    )
