from __future__ import annotations

import io
import json
from pathlib import Path
import tarfile

import pytest

from data.public_data import _safe_extract_tar, read_jsonl, validate_public_data


def test_read_jsonl_streams_file_without_read_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "records.jsonl"
    path.write_text('{"id": 1}\n\n{"id": 2}\n', encoding="utf-8")

    def fail_read_text(*args: object, **kwargs: object) -> str:
        raise AssertionError("read_jsonl must stream instead of loading the whole file")

    monkeypatch.setattr(Path, "read_text", fail_read_text)
    assert read_jsonl(path) == [{"id": 1}, {"id": 2}]


def test_read_jsonl_reports_source_line_for_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    path.write_text('{"id": 1}\n\nnot-json\n', encoding="utf-8")

    with pytest.raises(RuntimeError, match=r"records\.jsonl at line 3"):
        read_jsonl(path)


def _write_tar(path: Path, members: list[tuple[tarfile.TarInfo, bytes]]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for info, content in members:
            archive.addfile(info, io.BytesIO(content))


def test_safe_extract_tar_extracts_regular_files(tmp_path: Path) -> None:
    archive_path = tmp_path / "screenshots.tar.gz"
    info = tarfile.TarInfo("trajectory-1/0.png")
    info.size = len(b"image")
    _write_tar(archive_path, [(info, b"image")])

    destination = tmp_path / "expanded"
    _safe_extract_tar(archive_path, destination)

    assert (destination / "trajectory-1" / "0.png").read_bytes() == b"image"


@pytest.mark.parametrize("member_name", ["../escape.txt", "/absolute.txt"])
def test_safe_extract_tar_rejects_path_traversal(tmp_path: Path, member_name: str) -> None:
    archive_path = tmp_path / "unsafe.tar.gz"
    info = tarfile.TarInfo(member_name)
    info.size = 1
    _write_tar(archive_path, [(info, b"x")])

    destination = tmp_path / "expanded"
    with pytest.raises(RuntimeError, match="unsafe archive member path"):
        _safe_extract_tar(archive_path, destination)

    assert not destination.exists()


def test_safe_extract_tar_rejects_links(tmp_path: Path) -> None:
    archive_path = tmp_path / "unsafe-link.tar.gz"
    info = tarfile.TarInfo("linked")
    info.type = tarfile.SYMTYPE
    info.linkname = "../outside"
    _write_tar(archive_path, [(info, b"")])

    destination = tmp_path / "expanded"
    with pytest.raises(RuntimeError, match="non-file archive member"):
        _safe_extract_tar(archive_path, destination)

    assert not destination.exists()


def test_validate_public_data_accepts_consistent_minimal_dataset(tmp_path: Path) -> None:
    (tmp_path / "haystacks").mkdir()
    (tmp_path / "screenshots" / "trajectory-1").mkdir(parents=True)
    (tmp_path / "screenshots" / "trajectory-1" / "0.png").write_bytes(b"image")
    (tmp_path / "questions.jsonl").write_text(
        json.dumps(
            {
                "id": "question-1",
                "domain": "web",
                "question": "What happened?",
                "image": None,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "trajectories.jsonl").write_text(
        json.dumps(
            {
                "id": "trajectory-1",
                "domain": "web",
                "states": [{"screenshot": "screenshots/trajectory-1/0.png"}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "haystacks" / "lme_v2_small.json").write_text(
        json.dumps({"question-1": ["trajectory-1"]}),
        encoding="utf-8",
    )

    result = validate_public_data(tmp_path, tier="small")

    assert result["questions"] == 1
    assert result["trajectories"] == 1
