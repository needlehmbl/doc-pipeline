import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.watch import move_to


def test_move_to_moves_and_creates_dest(tmp_path):
    src = tmp_path / "a.pdf"
    src.write_bytes(b"x")
    dest = tmp_path / "out" / "nested"
    moved = move_to(src, str(dest))
    assert moved.exists()
    assert not src.exists()
    assert moved.parent == dest


def test_move_to_handles_collision(tmp_path):
    src = tmp_path / "a.pdf"
    src.write_bytes(b"x")
    dest = tmp_path / "out"
    dest.mkdir()
    (dest / "a.pdf").write_bytes(b"existing")

    first = move_to(src, str(dest))
    assert first.exists()
    assert first.name != "a.pdf"

    src2 = tmp_path / "b.pdf"
    src2.write_bytes(b"y")
    second = move_to(src2, str(dest))
    assert second.exists()
    assert second.name != first.name