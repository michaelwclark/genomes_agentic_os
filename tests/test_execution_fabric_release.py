from __future__ import annotations

from importlib import resources
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/release/build-execution-fabric-release.py"


def test_published_distribution_validation_is_release_gated() -> None:
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    for tree in ("harness", "templates", "operating-manual", "schemas"):
        assert f"recursive-include {tree} *" in manifest
    workflow = (ROOT / ".github/workflows/test.yml").read_text(encoding="utf-8")
    assert "python scripts/qa/validate-python-distributions.py" in workflow


def test_release_versions_and_contracts_are_coherent() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--validate-only"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_release_builder_emits_digest_locked_portable_assets(tmp_path: Path) -> None:
    digest = "a" * 64
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--output-dir",
            str(tmp_path),
            "--control-plane-image",
            f"ghcr.io/michaelwclark/control@sha256:{digest}",
            "--witness-image",
            f"ghcr.io/michaelwclark/witness@sha256:{digest}",
            "--worker-image",
            f"ghcr.io/michaelwclark/worker@sha256:{digest}",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    manifest = json.loads(
        (tmp_path / "execution-fabric-release-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["python_package"]["version"] == "0.4.0"
    assert "@sha256:" in manifest["images"]["control_plane"]
    assert "@sha256:" in manifest["images"]["worker"]
    assert (tmp_path / "execution-fabric-emergency-bundle.tar.gz").is_file()
    assert "execution-fabric-image-lock.json" in (
        tmp_path / "SHA256SUMS"
    ).read_text(encoding="utf-8")


def test_wheel_resource_index_keeps_large_assets_out_of_installed_root() -> None:
    index = resources.files("genomes_agentic_os").joinpath(
        "resources/release-assets.json"
    )
    value = json.loads(index.read_text(encoding="utf-8"))
    assert value["portable_bundle"].endswith(".tar.gz")
    assert value["release_url_template"].startswith("https://github.com/")


def test_portable_archives_are_reproducible(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    image = (
        "ghcr.io/michaelwclark/fabric@sha256:"
        + "b" * 64
    )
    for output in (first, second):
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--output-dir",
                str(output),
                "--control-plane-image",
                image,
                "--witness-image",
                image,
                "--worker-image",
                image,
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
    for name in (
        "execution-fabric-emergency-bundle.tar.gz",
        "execution-fabric-config-schema.tar.gz",
    ):
        assert (first / name).read_bytes() == (second / name).read_bytes()
