from pathlib import Path
from unittest.mock import patch

from memory_modules.trajectory_store import relative_symlink


def test_relative_symlink_falls_back_to_copy_when_relpath_is_unavailable(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(b"screenshot")
    destination = tmp_path / "nested" / "destination.png"

    with patch("memory_modules.trajectory_store.os.path.relpath", side_effect=ValueError("cross drive")):
        relative_symlink(source, destination)

    assert destination.read_bytes() == b"screenshot"
    assert not destination.is_symlink()

