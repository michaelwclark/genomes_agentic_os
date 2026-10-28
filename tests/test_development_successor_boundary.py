"""Real scratch-filesystem admission controls; no operator environment files are read."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys
from typing import Any

import pytest

from genomes_agentic_os import development_successor_binding as admission
from genomes_agentic_os.development_delivery import DevelopmentDeliveryError
from test_development_delivery import _git


@pytest.fixture
def protected_tree(tmp_path: Path) -> dict[str, Any]:
    """Create a genuine dirty-capable Git checkout and its ordinary index."""
    repository = tmp_path.resolve() / "predecessor"
    repository.mkdir()
    _git("init", "-b", "protected", cwd=repository)
    _git("config", "user.name", "Native boundary test", cwd=repository)
    _git("config", "user.email", "boundary@example.invalid", cwd=repository)
    (repository / "README.md").write_text("original source\n")
    _git("add", "README.md", cwd=repository)
    _git("commit", "-m", "test: original source", cwd=repository)
    return {"worktree": {"path": str(repository), "branch": "protected"}}


@pytest.mark.parametrize("relative", [
    ".env", ".envs/local/postgres", "private.env", "config/private.env.local",
    "config/.ENV.production", "config/private.ENV",
])
def test_known_environment_paths_are_recorded_without_opening(
    protected_tree: dict[str, Any], monkeypatch: pytest.MonkeyPatch, relative: str,
) -> None:
    """Nested, suffixed and case-varied environment paths never reach an open call."""
    root = Path(protected_tree["worktree"]["path"])
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("scratch-only secret sentinel\n")
    real_open = os.open
    forbidden = set(Path(relative).parts)
    def guarded_open(file: Any, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
        """Fail if observation attempts to open any excluded environment component."""
        if os.fspath(file) in forbidden:
            pytest.fail("excluded environment path was opened")
        return real_open(file, flags, mode, dir_fd=dir_fd)
    monkeypatch.setattr(admission.os, "open", guarded_open)
    result = admission.predecessor_boundary(protected_tree)
    assert result["changed_files"][relative] == {"excluded": "secret-or-dependency-boundary"}
    assert "scratch-only" not in str(result)


def test_boundary_retains_genuine_source_index_mode_and_final_symlink(
    protected_tree: dict[str, Any],
) -> None:
    """Ordinary source bytes/index and link text have exact independent digest oracles."""
    root = Path(protected_tree["worktree"]["path"])
    content = b"changed ordinary source\n"
    (root / "README.md").write_bytes(content)
    (root / "README.md").chmod(0o700)
    (root / "pointer").symlink_to(".envs/local/postgres")
    result = admission.predecessor_boundary(protected_tree)
    assert result["changed_files"]["README.md"] == {
        "sha256": hashlib.sha256(content).hexdigest(), "mode": 0o700,
    }
    assert result["index_sha256"] == hashlib.sha256((root / ".git/index").read_bytes()).hexdigest()
    assert result["changed_files"]["pointer"] == {
        "symlink_sha256": hashlib.sha256(b".envs/local/postgres").hexdigest(),
    }


def test_oversized_source_is_refused_before_opening(
    protected_tree: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real stat size must fit the byte budget before a content descriptor exists."""
    root = Path(protected_tree["worktree"]["path"])
    (root / "oversized.py").write_bytes(b"x" * 9)
    monkeypatch.setattr(admission, "MAX_PROTECTED_FILE_BYTES", 8)
    real_open = os.open
    def guarded_open(file: Any, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
        """Ensure rejection is pre-read and pre-open, using a real oversized file."""
        assert os.fspath(file) != "oversized.py"
        return real_open(file, flags, mode, dir_fd=dir_fd)
    monkeypatch.setattr(admission.os, "open", guarded_open)
    with pytest.raises(DevelopmentDeliveryError, match="per-file or aggregate byte bound"):
        admission.predecessor_boundary(protected_tree)


def test_changed_file_count_rejects_before_any_content_read(
    protected_tree: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The native Git inventory cannot trigger an unbounded number of content reads."""
    root = Path(protected_tree["worktree"]["path"])
    for number in range(3):
        (root / f"source-{number}.py").write_text("x")
    monkeypatch.setattr(admission, "MAX_PROTECTED_FILES", 2)
    def forbidden_open(*args: Any, **kwargs: Any) -> int:
        """Any observation descriptor would be premature after count overflow."""
        pytest.fail("file count overflow opened content")
    monkeypatch.setattr(admission.os, "open", forbidden_open)
    with pytest.raises(DevelopmentDeliveryError, match="changed-file count bound"):
        admission.predecessor_boundary(protected_tree)


def test_aggregate_byte_bound_includes_real_index_and_all_source(
    protected_tree: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Several individually admissible files must still share one finite byte budget."""
    root = Path(protected_tree["worktree"]["path"])
    (root / "a.py").write_bytes(b"a" * 8)
    (root / "b.py").write_bytes(b"b" * 8)
    monkeypatch.setattr(admission, "MAX_PROTECTED_FILE_BYTES", 8)
    monkeypatch.setattr(admission, "MAX_PROTECTED_TOTAL_BYTES", (root / ".git/index").stat().st_size + 12)
    with pytest.raises(DevelopmentDeliveryError, match="per-file or aggregate byte bound"):
        admission.predecessor_boundary(protected_tree)


def test_real_fifo_and_ancestor_symlink_are_rejected_without_target_read(tmp_path: Path) -> None:
    """Special nodes cannot block observation or route content outside the root."""
    root = tmp_path.resolve()
    os.mkfifo(root / "pipe")
    with pytest.raises(DevelopmentDeliveryError, match="not an ordinary file"):
        admission._protected_entry(root, Path("pipe"), limit=100, remaining=100)
    outside = root / "outside"
    outside.mkdir()
    (outside / "private.env").write_text("scratch sentinel")
    (root / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(DevelopmentDeliveryError, match="observation failed"):
        admission._protected_entry(root, Path("linked/private.env"), limit=100, remaining=100)


def test_real_file_growth_during_chunked_read_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A genuine append between reads cannot evade the declared byte cap."""
    root = tmp_path.resolve()
    source = root / "ordinary.py"
    source.write_bytes(b"12345678")
    inode = source.stat().st_ino
    real_read = os.read
    appended = False
    def append_after_read(descriptor: int, count: int) -> bytes:
        """Use the real read then append one byte to its real file once."""
        nonlocal appended
        chunk = real_read(descriptor, count)
        if os.fstat(descriptor).st_ino == inode and not appended:
            with source.open("ab") as handle:
                handle.write(b"9")
            appended = True
        return chunk
    monkeypatch.setattr(admission.os, "read", append_after_read)
    with pytest.raises(DevelopmentDeliveryError, match="grew beyond its byte bound"):
        admission._protected_entry(root, Path("ordinary.py"), limit=8, remaining=8)
    assert appended
    assert source.read_bytes() == b"123456789"


def test_real_symlink_replacement_before_open_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A genuine replacement after lstat cannot cause the target contents to be opened."""
    root = tmp_path.resolve()
    source = root / "ordinary.py"
    source.write_text("ordinary source")
    target = root / "private.env"
    target.write_text("scratch-only target")
    real_open = os.open
    replaced = False
    def replace_before_open(file: Any, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
        """Introduce the real race only at the final ordinary-file open boundary."""
        nonlocal replaced
        if os.fspath(file) == "ordinary.py" and not flags & os.O_DIRECTORY:
            source.unlink()
            source.symlink_to(target)
            replaced = True
        return real_open(file, flags, mode, dir_fd=dir_fd)
    monkeypatch.setattr(admission.os, "open", replace_before_open)
    with pytest.raises(DevelopmentDeliveryError, match="observation failed"):
        admission._protected_entry(root, Path("ordinary.py"), limit=100, remaining=100)
    assert replaced
    assert source.is_symlink()


def test_proof_json_size_refuses_before_open_and_final_symlink_is_never_followed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The separately declared JSON bound also applies before reading ordinary proof bytes."""
    source = tmp_path / "proof.json"
    source.write_text('{"value": "too large"}')
    monkeypatch.setattr(admission, "MAX_PROOF_BYTES", 8)
    def forbidden_open(*args: Any, **kwargs: Any) -> int:
        """An oversized proof or final symlink must be rejected without opening content."""
        pytest.fail("inadmissible proof was opened")
    monkeypatch.setattr(admission.os, "open", forbidden_open)
    with pytest.raises(DevelopmentDeliveryError, match="bounded JSON size"):
        admission.read_json(source)
    link = tmp_path / "link.json"
    link.symlink_to(source)
    with pytest.raises(DevelopmentDeliveryError, match="ordinary regular file"):
        admission.read_json(link)


@pytest.mark.parametrize("name", [
    " leading.py", "trailing.py ", "\tleading.py", "leading\nline.py",
    "leading\rline.py", "leading\r\nline.py", "trailing.py\n",
])
def test_real_nul_delimited_git_filename_keeps_whitespace_and_detects_changed_bytes(
    protected_tree: dict[str, Any], name: str,
) -> None:
    """Native Git inventories retain the exact path and protect genuinely changed dirty bytes."""
    root = Path(protected_tree["worktree"]["path"])
    source = root / name
    before = b"before\n"
    after = b"after with different protected bytes\n"
    source.write_bytes(before)
    first = admission.predecessor_boundary(protected_tree)
    assert set(first["changed_files"]) == {name}
    assert first["changed_files"][name]["sha256"] == hashlib.sha256(before).hexdigest()
    source.write_bytes(after)
    second = admission.predecessor_boundary(protected_tree)
    assert set(second["changed_files"]) == {name}
    assert second["changed_files"][name]["sha256"] == hashlib.sha256(after).hexdigest()
    assert first["status_sha256"] == second["status_sha256"]
    assert first != second


def test_native_observation_preserves_all_embedded_crlf_and_nul_stdout() -> None:
    """Real child stdout is decoded without trimming or universal-newline normalization."""
    content = " leading\r\nname\x00trailing\n\x00\n\n"
    result = admission.native([sys.executable, "-c", "import sys; sys.stdout.buffer.write(" + repr(content.encode()) + ")"])
    assert result == content
    assert result.endswith("\n\n")


def test_scalar_git_observation_removes_only_one_record_lf(protected_tree: dict[str, Any]) -> None:
    """A scalar Git value ending in LF retains that data when its record LF is removed."""
    root = Path(protected_tree["worktree"]["path"])
    _git("config", "probe.value", "value ending in LF\n", cwd=root)
    assert admission.git(root, "config", "--get", "probe.value") == "value ending in LF\n"


def test_native_invalid_text_encoding_refuses_without_echoing_raw_bytes() -> None:
    """Unsupported native output fails closed before a corrupted path can enter a receipt."""
    with pytest.raises(DevelopmentDeliveryError, match="unsupported text encoding"):
        admission.native([sys.executable, "-c", "import sys; sys.stdout.buffer.write(bytes([255]))"])
