from __future__ import annotations

from pathlib import Path
import subprocess


WRAPPER = Path(__file__).parents[1] / "harness/bin/agentic-os-los-fullsail-updater"


def _controller(root: Path) -> None:
    path = (
        root
        / "lib/programs/domains/los/los_fullsail_updater/scripts/fullsail_updater.py"
    )
    path.parent.mkdir(parents=True)
    path.write_text("# wrapper selection test\n", encoding="utf-8")


def _candidate(path: Path, marker: str, *, imports: bool = True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    probe = "exit 0" if imports else "exit 1"
    path.write_text(
        "#!/bin/sh\n"
        f"if [ \"${{1:-}}\" = \"-c\" ]; then {probe}; fi\n"
        f"printf '%s\\n' '{marker}'\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _run(wrapper_home: Path, root: Path, **extra: str) -> subprocess.CompletedProcess[str]:
    env = {
        "HOME": str(wrapper_home),
        "PATH": f"{wrapper_home / 'path'}:/usr/bin:/bin",
        "AGENTIC_OS_ROOT": str(root),
        **extra,
    }
    return subprocess.run(
        ["/bin/sh", str(WRAPPER), "status"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def test_fullsail_wrapper_prefers_explicit_runtime(tmp_path: Path) -> None:
    home = tmp_path / "home"
    root = tmp_path / "root"
    _controller(root)
    explicit = _candidate(tmp_path / "explicit/python", "explicit")
    _candidate(
        home
        / "Library/Application Support/AgenticOS/development-delivery-runtime/bin/python",
        "alias",
    )

    result = _run(home, root, AGENTIC_OS_PYTHON=str(explicit))

    assert result.returncode == 0
    assert result.stdout.strip() == "explicit"


def test_fullsail_wrapper_prefers_alias_and_skips_invalid_candidate(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    root = tmp_path / "root"
    _controller(root)
    _candidate(
        home
        / "Library/Application Support/AgenticOS/development-delivery-runtime/bin/python",
        "invalid",
        imports=False,
    )
    _candidate(
        home / "Library/Application Support/AgenticOS/layout-v2-runtime/bin/python",
        "valid-alias",
    )
    _candidate(home / "path/python3", "system-python")

    result = _run(home, root)

    assert result.returncode == 0
    assert result.stdout.strip() == "valid-alias"


def test_fullsail_wrapper_rejects_unmanaged_interpreter(tmp_path: Path) -> None:
    home = tmp_path / "home"
    root = tmp_path / "root"
    _controller(root)
    _candidate(home / "path/python3", "invalid-system", imports=False)

    result = _run(home, root)

    assert result.returncode != 0
    assert "Agentic OS Python runtime not found" in result.stderr
