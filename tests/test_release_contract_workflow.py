"""Static and fixture tests for the reusable release contract."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "release-contract.yml"
RELEASE_WORKFLOW_PATH = ROOT / ".github" / "workflows" / "release.yml"
SCRIPT_PATH = ROOT / "scripts" / "release" / "release-contract.py"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "release_contract" / "decision-matrix.json"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("release_contract", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CONTRACT = _module()


def _workflow() -> dict[str, object]:
    # BaseLoader keeps the YAML 1.2 key `on` from becoming YAML 1.1 boolean True.
    return yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def _release_workflow() -> dict[str, object]:
    return yaml.load(
        RELEASE_WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader
    )


def test_workflow_call_surface_is_secretless_and_least_privilege() -> None:
    workflow = _workflow()
    workflow_call = workflow["on"]["workflow_call"]
    assert "secrets" not in workflow_call
    assert set(workflow_call["inputs"]) == {
        "version",
        "tag",
        "release_ref",
        "target_sha",
        "tag_mode",
        "artifact_name",
        "artifact_run_id",
        "asset_manifest",
        "notes_file",
        "generate_notes",
        "prerelease",
        "dry_run",
    }
    assert set(workflow_call["outputs"]) == {
        "tag",
        "version",
        "target_sha",
        "release_id",
        "release_url",
        "created",
        "repaired",
        "assets_uploaded",
        "assets_receipt",
    }
    assert workflow["permissions"] == {"actions": "read", "contents": "write"}
    assert "concurrency" not in workflow
    concurrency = workflow["jobs"]["contract"]["concurrency"]
    assert concurrency["cancel-in-progress"] == "false"
    assert concurrency["group"].startswith(
        "release-${{ github.repository }}-"
    )


def test_every_action_is_sha_pinned_and_host_checkout_matches_workflow_sha() -> None:
    workflow = _workflow()
    steps = workflow["jobs"]["contract"]["steps"]
    action_steps = [step for step in steps if "uses" in step]
    assert action_steps
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", step["uses"]) for step in action_steps)
    checkout = action_steps[0]
    assert "job)).workflow_repository" in checkout["with"]["repository"]
    assert "job)).workflow_sha" in checkout["with"]["ref"]
    assert checkout["with"]["persist-credentials"] == "false"


def test_current_and_cross_run_artifact_paths_are_mutually_exclusive() -> None:
    steps = _workflow()["jobs"]["contract"]["steps"]
    current = next(step for step in steps if step["name"].startswith("Download a current"))
    cross = next(step for step in steps if step["name"].startswith("Download a cross"))
    assert "artifact_run_id == ''" in current["if"]
    assert "artifact_run_id == format('{0}', github.run_id)" in current["if"]
    assert "github-token" not in current["with"]
    assert "run-id" not in current["with"]
    assert "artifact_run_id != ''" in cross["if"]
    assert "artifact_run_id != format('{0}', github.run_id)" in cross["if"]
    assert cross["with"]["github-token"] == "${{ github.token }}"
    assert cross["with"]["repository"] == "${{ github.repository }}"
    assert cross["with"]["run-id"] == "${{ inputs.artifact_run_id }}"


def test_agentic_os_release_adapter_uses_the_additive_contract() -> None:
    workflow = _release_workflow()
    source = RELEASE_WORKFLOW_PATH.read_text(encoding="utf-8")
    release_job = workflow["jobs"]["github-release"]
    assert release_job["uses"] == "./.github/workflows/release-contract.yml"
    assert release_job["permissions"] == {"actions": "read", "contents": "write"}
    assert release_job["with"]["tag_mode"] == "verify"
    manifest = release_job["with"]["asset_manifest"].splitlines()
    assert len(manifest) == 8
    assert "execution-fabric-release-manifest.json" in manifest
    assert "SHA256SUMS" in manifest
    assert "secrets" not in release_job
    assert "--validate-stable-version" in source
    assert "exit 73" not in source


@pytest.mark.parametrize("case", json.loads(FIXTURE_PATH.read_text(encoding="utf-8")))
def test_decision_matrix(case: dict[str, object]) -> None:
    target = "a" * 40
    tag_sha = case["tag_sha"]
    if tag_sha == "TARGET":
        tag_sha = target
    elif tag_sha == "OTHER":
        tag_sha = "b" * 40
    arguments = {
        "tag_sha": tag_sha,
        "target_sha": target,
        "tag_mode": case["tag_mode"],
        "release_exists": case["release_exists"],
        "existing_assets": case["existing_assets"],
        "expected_assets": case["expected_assets"],
    }
    if "violation" in case:
        with pytest.raises(CONTRACT.ContractViolation, match=str(case["violation"])):
            CONTRACT.decide(**arguments)
        return
    decision = CONTRACT.decide(**arguments)
    assert {
        "create_tag": decision.create_tag,
        "create_release": decision.create_release,
        "missing_assets": list(decision.missing_assets),
    } == case["expected"]


@pytest.mark.parametrize(
    "manifest",
    ["bundle.tgz\nbundle.tgz", "../bundle.tgz", "nested/bundle.tgz", "/tmp/bundle.tgz"],
)
def test_manifest_rejects_duplicate_or_non_flat_asset_names(manifest: str) -> None:
    with pytest.raises(CONTRACT.ContractViolation):
        CONTRACT.parse_manifest(manifest)


def test_workflow_has_explicit_failure_and_readback_markers() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "CONTRACT_VIOLATION" in source
    assert "PROVIDER_FAILURE" in source
    assert "final_tag_sha = provider.tag_sha(tag)" in source
    assert "final_release = provider.release(tag)" in source
    assert '"--clobber"' not in source
    assert "delete" not in source.lower()


def _environment(artifact_dir: Path, *, dry_run: bool) -> dict[str, str]:
    return {
        "RELEASE_CONTRACT_REPOSITORY": "example/repository",
        "RELEASE_CONTRACT_VERSION": "1.2.3",
        "RELEASE_CONTRACT_TAG": "",
        "RELEASE_CONTRACT_RELEASE_REF": "main",
        "RELEASE_CONTRACT_TARGET_SHA": "a" * 40,
        "RELEASE_CONTRACT_TAG_MODE": "create",
        "RELEASE_CONTRACT_ARTIFACT_DIR": str(artifact_dir),
        "RELEASE_CONTRACT_ARTIFACT_RUN_ID": "",
        "RELEASE_CONTRACT_ASSET_MANIFEST": "bundle.tgz\nSHA256SUMS",
        "RELEASE_CONTRACT_NOTES_FILE": "",
        "RELEASE_CONTRACT_GENERATE_NOTES": "true",
        "RELEASE_CONTRACT_PRERELEASE": "false",
        "RELEASE_CONTRACT_DRY_RUN": str(dry_run).lower(),
        "GITHUB_RUN_ID": "900",
    }


class _FakeProvider:
    def __init__(
        self,
        *,
        release: dict[str, object] | None,
        tag_sha: str | None,
        listed_releases: list[dict[str, object]] | None = None,
    ) -> None:
        self.release_state = release
        self.tag_state = tag_sha
        self.listed_release_state = listed_releases or []
        self.mutations: list[tuple[str, str]] = []
        self.reads: list[str] = []

    def resolve_commit(self, value: str) -> str:
        self.reads.append("commit")
        return value

    def compare_status(self, release_ref: str, target_sha: str) -> str:
        self.reads.append("ancestry")
        return "behind"

    def artifact_run_source(self, run_id: str) -> tuple[str, str]:
        self.reads.append("artifact_run")
        return "a" * 40, "example/repository"

    def tag_sha(self, tag: str) -> str | None:
        self.reads.append("tag")
        return self.tag_state

    def release(self, tag: str) -> dict[str, object] | None:
        self.reads.append("release")
        return self.release_state

    def releases(self) -> tuple[dict[str, object], ...]:
        self.reads.append("releases")
        return tuple(self.listed_release_state)

    def create_tag(self, tag: str, target_sha: str) -> None:
        self.mutations.append(("create_annotated_tag", tag))
        self.tag_state = target_sha

    def create_release(self, **values: object) -> None:
        tag = str(values["tag"])
        self.mutations.append(("create_release", tag))
        self.release_state = {
            "id": 42,
            "html_url": "https://example.test/release",
            "tag_name": tag,
            "draft": False,
            "prerelease": bool(values["prerelease"]),
            "assets": [],
        }

    def upload(self, tag: str, asset: Path) -> None:
        self.mutations.append(("upload", asset.name))
        assert self.release_state is not None
        assets = self.release_state["assets"]
        assert isinstance(assets, list)
        content = asset.read_bytes()
        assets.append(
            {
                "name": asset.name,
                "state": "uploaded",
                "size": len(content),
                "digest": f"sha256:{hashlib.sha256(content).hexdigest()}",
            }
        )


def test_dry_run_performs_guards_without_provider_mutations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "bundle.tgz").write_bytes(b"bundle")
    (tmp_path / "SHA256SUMS").write_text("digest", encoding="utf-8")
    provider = _FakeProvider(release=None, tag_sha=None)
    outputs: dict[str, str] = {}
    monkeypatch.setattr(CONTRACT, "GitHubProvider", lambda repository: provider)
    monkeypatch.setattr(CONTRACT, "_write_outputs", outputs.update)

    CONTRACT.run(_environment(tmp_path, dry_run=True))

    assert provider.mutations == []
    assert set(provider.reads) >= {"commit", "ancestry", "tag", "release"}
    assert outputs["created"] == "false"
    assert outputs["repaired"] == "false"
    assert outputs["assets_uploaded"] == "0"


def test_existing_partial_release_uploads_only_the_missing_asset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "bundle.tgz").write_bytes(b"bundle")
    (tmp_path / "SHA256SUMS").write_text("digest", encoding="utf-8")
    provider = _FakeProvider(
        tag_sha="a" * 40,
        release={
            "id": 42,
            "html_url": "https://example.test/release",
            "tag_name": "v1.2.3",
            "draft": False,
            "prerelease": False,
            "assets": [
                {
                    "name": "bundle.tgz",
                    "state": "uploaded",
                    "size": 6,
                    "digest": (
                        "sha256:1e6ed65d77d6364eeaed5a745ba5c498"
                        "5ae2b700dd85d7cf7f027bdf294a33fc"
                    ),
                }
            ],
        },
    )
    outputs: dict[str, str] = {}
    monkeypatch.setattr(CONTRACT, "GitHubProvider", lambda repository: provider)
    monkeypatch.setattr(CONTRACT, "_write_outputs", outputs.update)

    CONTRACT.run(_environment(tmp_path, dry_run=False))

    assert provider.mutations == [("upload", "SHA256SUMS")]
    assert outputs["created"] == "false"
    assert outputs["repaired"] == "true"
    assert outputs["assets_uploaded"] == "1"
    assert json.loads(outputs["assets_receipt"]) == [
        {
            "name": "bundle.tgz",
            "size": 6,
            "digest": (
                "sha256:1e6ed65d77d6364eeaed5a745ba5c498"
                "5ae2b700dd85d7cf7f027bdf294a33fc"
            ),
        },
        {
            "name": "SHA256SUMS",
            "size": 6,
            "digest": (
                "sha256:0bf474896363505e5ea5e5d6ace8ebfb"
                "13a760a409b1fb467d428fc716f9f284"
            ),
        },
    ]


def test_fresh_release_creates_tag_release_and_all_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "bundle.tgz").write_bytes(b"bundle")
    (tmp_path / "SHA256SUMS").write_text("digest", encoding="utf-8")
    provider = _FakeProvider(release=None, tag_sha=None)
    outputs: dict[str, str] = {}
    monkeypatch.setattr(CONTRACT, "GitHubProvider", lambda repository: provider)
    monkeypatch.setattr(CONTRACT, "_write_outputs", outputs.update)

    CONTRACT.run(_environment(tmp_path, dry_run=False))

    assert provider.mutations == [
        ("create_annotated_tag", "v1.2.3"),
        ("create_release", "v1.2.3"),
        ("upload", "bundle.tgz"),
        ("upload", "SHA256SUMS"),
    ]
    assert outputs["created"] == "true"
    assert outputs["repaired"] == "false"
    assert outputs["assets_uploaded"] == "2"
    assert outputs["release_id"] == "42"
    assert outputs["release_url"] == "https://example.test/release"
    assert json.loads(outputs["assets_receipt"]) == [
        {
            "name": "bundle.tgz",
            "size": 6,
            "digest": (
                "sha256:1e6ed65d77d6364eeaed5a745ba5c498"
                "5ae2b700dd85d7cf7f027bdf294a33fc"
            ),
        },
        {
            "name": "SHA256SUMS",
            "size": 6,
            "digest": (
                "sha256:0bf474896363505e5ea5e5d6ace8ebfb"
                "13a760a409b1fb467d428fc716f9f284"
            ),
        },
    ]


def test_cross_run_artifact_must_match_target_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "bundle.tgz").write_bytes(b"bundle")
    (tmp_path / "SHA256SUMS").write_text("digest", encoding="utf-8")
    provider = _FakeProvider(release=None, tag_sha=None)
    monkeypatch.setattr(CONTRACT, "GitHubProvider", lambda repository: provider)
    monkeypatch.setattr(
        provider,
        "artifact_run_source",
        lambda run_id: ("b" * 40, "example/repository"),
    )
    environment = _environment(tmp_path, dry_run=True)
    environment["RELEASE_CONTRACT_ARTIFACT_RUN_ID"] = "123"

    with pytest.raises(CONTRACT.ContractViolation, match="workflow run source"):
        CONTRACT.run(environment)


def test_artifact_file_outside_manifest_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "bundle.tgz").write_bytes(b"bundle")
    (tmp_path / "SHA256SUMS").write_text("digest", encoding="utf-8")
    (tmp_path / "unlisted.bin").write_bytes(b"unexpected")
    provider = _FakeProvider(release=None, tag_sha=None)
    monkeypatch.setattr(CONTRACT, "GitHubProvider", lambda repository: provider)

    with pytest.raises(CONTRACT.ContractViolation, match="outside asset_manifest"):
        CONTRACT.run(_environment(tmp_path, dry_run=True))


def test_version_gate_is_explicitly_semver_only() -> None:
    CONTRACT.validate_version("1.2.3-rc.1")
    with pytest.raises(CONTRACT.ContractViolation, match="SemVer"):
        CONTRACT.validate_version("1.2.3rc1")


def test_agentic_os_adapter_rejects_non_stable_semver_before_builds() -> None:
    CONTRACT.validate_stable_version("1.2.3")
    with pytest.raises(CONTRACT.ContractViolation, match="stable SemVer"):
        CONTRACT.validate_stable_version("1.2.3-rc.1")
    with pytest.raises(CONTRACT.ContractViolation, match="stable SemVer"):
        CONTRACT.validate_stable_version("1.2.3+build.7")


def test_provider_not_found_detection_requires_exact_gh_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        [
            subprocess.CompletedProcess(
                ["gh"], 1, "version 1.404.2", "gh: upstream failed (HTTP 503)"
            ),
            subprocess.CompletedProcess(
                ["gh"], 1, "", "gh: Not Found (HTTP 404)"
            ),
        ]
    )
    monkeypatch.setattr(CONTRACT.subprocess, "run", lambda *args, **kwargs: next(responses))
    provider = CONTRACT.GitHubProvider("example/repository")
    with pytest.raises(CONTRACT.ProviderFailure):
        provider.get("first", allow_not_found=True)
    assert provider.get("second", allow_not_found=True) is None


def test_missing_commit_detection_requires_exact_gh_422_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        [
            subprocess.CompletedProcess(
                ["gh"],
                1,
                "",
                "gh: validation failed for another reason (HTTP 422)",
            ),
            subprocess.CompletedProcess(
                ["gh"],
                1,
                "",
                f"gh: No commit found for SHA: {'a' * 40} (HTTP 422)",
            ),
        ]
    )
    monkeypatch.setattr(CONTRACT.subprocess, "run", lambda *args, **kwargs: next(responses))
    provider = CONTRACT.GitHubProvider("example/repository")
    with pytest.raises(CONTRACT.ProviderFailure):
        provider.get("first", allow_no_commit=True)
    assert provider.get("second", allow_no_commit=True) is None


def test_create_tag_builds_annotated_object_before_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = CONTRACT.GitHubProvider("example/repository")
    calls: list[tuple[str, dict[str, object]]] = []

    def post(path: str, payload: dict[str, object]) -> dict[str, object]:
        calls.append((path, payload))
        return {"sha": "b" * 40} if path.endswith("/git/tags") else {}

    monkeypatch.setattr(provider, "post", post)
    provider.create_tag("v1.2.3", "a" * 40)

    assert calls == [
        (
            "repos/example/repository/git/tags",
            {
                "tag": "v1.2.3",
                "message": "Release v1.2.3",
                "object": "a" * 40,
                "type": "commit",
            },
        ),
        (
            "repos/example/repository/git/refs",
            {"ref": "refs/tags/v1.2.3", "sha": "b" * 40},
        ),
    ]


def test_existing_draft_release_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _FakeProvider(
        tag_sha="a" * 40,
        release=None,
        listed_releases=[
            {
                "id": 42,
                "html_url": "https://example.test/release",
                "tag_name": "v1.2.3",
                "draft": True,
                "prerelease": False,
                "assets": [],
            }
        ],
    )
    environment = _environment(tmp_path, dry_run=True)
    environment["RELEASE_CONTRACT_ASSET_MANIFEST"] = ""
    monkeypatch.setattr(CONTRACT, "GitHubProvider", lambda repository: provider)

    with pytest.raises(CONTRACT.ContractViolation, match="draft"):
        CONTRACT.run(environment)


def test_open_asset_state_fails_closed() -> None:
    with pytest.raises(CONTRACT.ContractViolation, match="not fully uploaded"):
        CONTRACT._release_asset_receipts(
            {"assets": [{"name": "bundle.tgz", "state": "open"}]}
        )


def test_provider_asset_identity_mismatch_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "bundle.tgz").write_bytes(b"bundle")
    (tmp_path / "SHA256SUMS").write_text("digest", encoding="utf-8")
    provider = _FakeProvider(
        tag_sha="a" * 40,
        release={
            "id": 42,
            "html_url": "https://example.test/release",
            "tag_name": "v1.2.3",
            "draft": False,
            "prerelease": False,
            "assets": [
                {
                    "name": "bundle.tgz",
                    "state": "uploaded",
                    "size": 7,
                    "digest": "sha256:" + "b" * 64,
                }
            ],
        },
    )
    monkeypatch.setattr(CONTRACT, "GitHubProvider", lambda repository: provider)

    with pytest.raises(CONTRACT.ContractViolation, match="trusted artifact"):
        CONTRACT.run(_environment(tmp_path, dry_run=True))


def test_exact_integration_permission_failure_is_permanent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = subprocess.CompletedProcess(
        ["gh"],
        1,
        "",
        "gh: Resource not accessible by integration (HTTP 403)",
    )
    monkeypatch.setattr(CONTRACT.subprocess, "run", lambda *args, **kwargs: response)
    provider = CONTRACT.GitHubProvider("example/repository")

    with pytest.raises(CONTRACT.ContractViolation, match="permissions"):
        provider.get("repos/example/repository/releases")


def test_retryable_provider_failure_retains_sanitized_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = subprocess.CompletedProcess(
        ["gh"], 1, "", "gh: upstream unavailable (HTTP 503)"
    )
    monkeypatch.setattr(CONTRACT.subprocess, "run", lambda *args, **kwargs: response)
    provider = CONTRACT.GitHubProvider("example/repository")

    with pytest.raises(CONTRACT.ProviderFailure, match="upstream unavailable"):
        provider.get("repos/example/repository/releases")


def test_upload_permission_failure_is_permanent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = tmp_path / "bundle.tgz"
    asset.write_bytes(b"bundle")
    response = subprocess.CompletedProcess(
        ["gh"],
        1,
        "",
        "gh: Resource not accessible by integration (HTTP 403)",
    )
    monkeypatch.setattr(CONTRACT.subprocess, "run", lambda *args, **kwargs: response)
    provider = CONTRACT.GitHubProvider("example/repository")

    with pytest.raises(CONTRACT.ContractViolation, match="permission"):
        provider.upload("v1.2.3", asset)


def test_retryable_upload_failure_retains_sanitized_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = tmp_path / "bundle.tgz"
    asset.write_bytes(b"bundle")
    response = subprocess.CompletedProcess(
        ["gh"], 1, "", "gh: upstream unavailable (HTTP 503)"
    )
    monkeypatch.setattr(CONTRACT.subprocess, "run", lambda *args, **kwargs: response)
    provider = CONTRACT.GitHubProvider("example/repository")

    with pytest.raises(CONTRACT.ProviderFailure, match="upstream unavailable"):
        provider.upload("v1.2.3", asset)
