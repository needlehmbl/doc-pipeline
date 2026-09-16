import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extract.extractor import extract_csv, extract_text
from ingest.watch import list_pending


def test_extract_csv_renders_text(tmp_path):
    f = tmp_path / "orders.csv"
    f.write_text("vendor,amount\nAcme,10\nGlobex,20\n")
    text = extract_csv(f)
    assert "Acme" in text
    assert "10" in text


def test_extract_text_unsupported_raises(tmp_path):
    f = tmp_path / "notes.txt"
    f.write_text("hello")
    try:
        extract_text(f)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_list_pending_skips_unupported(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "b.txt").write_text("hi")
    (tmp_path / ".gitkeep").write_text("")
    pending = list_pending(str(tmp_path))
    assert [p.name for p in pending] == ["a.pdf"]