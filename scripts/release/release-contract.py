#!/usr/bin/env python3
"""Provider-read, additive-only GitHub release contract.

Exit 2 denotes a permanent contract violation. Exit 1 denotes a provider or
host failure that is safe to retry because every mutation is idempotent and
read back before success.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence
from urllib.parse import quote


SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
SHA = re.compile(r"^[0-9a-f]{40}$")
ASSET_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


class ContractViolation(RuntimeError):
    """A permanent input or provider-state mismatch; retrying cannot fix it."""


class ProviderFailure(RuntimeError):
    """A provider command failed in a way that is safe to retry."""


def _stderr_lines(stderr: str) -> tuple[str, ...]:
    return tuple(line.strip() for line in stderr.splitlines() if line.strip())


def _permission_denied(stderr: str) -> bool:
    return any(
        line.endswith("Resource not accessible by integration (HTTP 403)")
        for line in _stderr_lines(stderr)
    )


def _error_detail(stderr: str) -> str:
    lines = _stderr_lines(stderr)
    return "" if not lines else f": {lines[-1][:240]}"


@dataclass(frozen=True)
class Decision:
    """The additive actions required to converge one release."""

    create_tag: bool
    create_release: bool
    missing_assets: tuple[str, ...]

    @property
    def noop(self) -> bool:
        return not self.create_tag and not self.create_release and not self.missing_assets


@dataclass(frozen=True)
class AssetReceipt:
    """Provider-read identity for one immutable release asset."""

    name: str
    size: int
    digest: str


def parse_manifest(value: str) -> tuple[str, ...]:
    """Return a unique ordered tuple of safe, flat release filenames."""

    names = tuple(line.strip() for line in value.splitlines() if line.strip())
    if len(names) != len(set(names)):
        raise ContractViolation("asset_manifest contains duplicate filenames")
    for name in names:
        path = PurePosixPath(name)
        if path.name != name or name in {".", ".."} or "\x00" in name:
            raise ContractViolation(
                f"asset_manifest entry must be a flat filename: {name!r}"
            )
    return names


def validate_version(value: str) -> None:
    """Require canonical SemVer before any build or provider mutation."""

    if not SEMVER.fullmatch(value):
        raise ContractViolation("version must be SemVer without a v prefix")


def validate_stable_version(value: str) -> None:
    """Require stable SemVer for adapters whose artifact names use the raw version."""

    validate_version(value)
    match = SEMVER.fullmatch(value)
    assert match is not None
    if match.group(4) is not None or match.group(5) is not None:
        raise ContractViolation(
            "Agentic OS release adapter requires a stable SemVer version"
        )


def decide(
    *,
    tag_sha: str | None,
    target_sha: str,
    tag_mode: str,
    release_exists: bool,
    existing_assets: Sequence[str],
    expected_assets: Sequence[str],
) -> Decision:
    """Apply the tag/SHA/release/manifest idempotency matrix."""

    if tag_mode not in {"create", "verify"}:
        raise ContractViolation("tag_mode must be 'create' or 'verify'")
    if tag_sha is None and tag_mode == "verify":
        raise ContractViolation("tag_mode=verify requires an existing provider tag")
    if tag_sha is not None and tag_sha != target_sha:
        raise ContractViolation("provider tag does not resolve to target_sha")

    current = tuple(existing_assets)
    if len(current) != len(set(current)):
        raise ContractViolation("provider release contains duplicate asset names")
    expected = tuple(expected_assets)
    unexpected = sorted(set(current) - set(expected))
    if release_exists and unexpected:
        raise ContractViolation(
            "provider release has unexpected assets: " + ", ".join(unexpected)
        )
    missing = tuple(name for name in expected if name not in set(current))
    return Decision(
        create_tag=tag_sha is None,
        create_release=not release_exists,
        missing_assets=missing,
    )


class GitHubProvider:
    """Small `gh` transport that distinguishes 404 reads from other failures."""

    def __init__(self, repository: str) -> None:
        self.repository = repository

    def _run(
        self,
        args: Sequence[str],
        *,
        payload: Mapping[str, Any] | None = None,
        allow_not_found: bool = False,
        allow_no_commit: bool = False,
    ) -> Any | None:
        command = ["gh", *args]
        encoded = None if payload is None else json.dumps(payload)
        result = subprocess.run(
            command,
            input=encoded,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            exact_not_found = any(
                line.strip().endswith("Not Found (HTTP 404)")
                for line in result.stderr.splitlines()
            )
            exact_no_commit = any(
                line.strip().startswith("gh: No commit found for SHA:")
                and line.strip().endswith("(HTTP 422)")
                for line in result.stderr.splitlines()
            )
            if _permission_denied(result.stderr):
                raise ContractViolation(
                    "provider token lacks the permissions required by the release contract"
                )
            if (allow_not_found and exact_not_found) or (
                allow_no_commit and exact_no_commit
            ):
                return None
            raise ProviderFailure(
                f"provider command failed ({result.returncode}): "
                f"{' '.join(command[:4])}{_error_detail(result.stderr)}"
            )
        if not result.stdout.strip():
            return {}
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ProviderFailure("provider returned non-JSON output") from exc

    def get(
        self,
        path: str,
        *,
        allow_not_found: bool = False,
        allow_no_commit: bool = False,
    ) -> Any | None:
        return self._run(
            ["api", "--method", "GET", path],
            allow_not_found=allow_not_found,
            allow_no_commit=allow_no_commit,
        )

    def post(self, path: str, payload: Mapping[str, Any]) -> Any:
        return self._run(
            ["api", "--method", "POST", path, "--input", "-"], payload=payload
        )

    def resolve_commit(self, value: str) -> str:
        response = self.get(
            f"repos/{self.repository}/commits/{quote(value, safe='')}",
            allow_not_found=True,
            allow_no_commit=True,
        )
        if response is None:
            raise ContractViolation("target_sha does not exist in the provider repository")
        if not isinstance(response, dict):
            raise ProviderFailure("provider returned an invalid commit")
        sha = response.get("sha")
        if not isinstance(sha, str) or not SHA.fullmatch(sha):
            raise ProviderFailure("provider returned an invalid commit SHA")
        return sha

    def tag_sha(self, tag: str) -> str | None:
        response = self.get(
            f"repos/{self.repository}/git/ref/tags/{quote(tag, safe='')}",
            allow_not_found=True,
        )
        if response is None:
            return None
        if not isinstance(response, dict) or not isinstance(response.get("object"), dict):
            raise ProviderFailure("provider returned an invalid tag reference")
        target = response["object"]
        for _ in range(8):
            object_type = target.get("type")
            sha = target.get("sha")
            if not isinstance(sha, str) or not SHA.fullmatch(sha):
                raise ProviderFailure("provider tag returned an invalid object SHA")
            if object_type == "commit":
                return sha
            if object_type != "tag":
                raise ContractViolation(
                    f"provider tag resolves to unsupported object type: {object_type!r}"
                )
            annotated = self.get(f"repos/{self.repository}/git/tags/{sha}")
            if not isinstance(annotated, dict) or not isinstance(
                annotated.get("object"), dict
            ):
                raise ProviderFailure("provider returned an invalid annotated tag")
            target = annotated["object"]
        raise ContractViolation("annotated tag chain exceeds eight objects")

    def compare_status(self, release_ref: str, target_sha: str) -> str:
        basehead = quote(f"{release_ref}...{target_sha}", safe="")
        response = self.get(
            f"repos/{self.repository}/compare/{basehead}", allow_not_found=True
        )
        if response is None:
            raise ContractViolation("release_ref does not exist in the provider repository")
        if not isinstance(response, dict) or not isinstance(response.get("status"), str):
            raise ProviderFailure("provider returned an invalid comparison")
        return response["status"]

    def artifact_run_source(self, run_id: str) -> tuple[str, str]:
        response = self.get(
            f"repos/{self.repository}/actions/runs/{quote(run_id, safe='')}",
            allow_not_found=True,
        )
        if response is None:
            raise ContractViolation("artifact_run_id does not exist in the repository")
        if not isinstance(response, dict) or not isinstance(
            response.get("head_repository"), dict
        ):
            raise ProviderFailure("provider returned an invalid artifact workflow run")
        head_sha = response.get("head_sha")
        repository = response["head_repository"].get("full_name")
        if not isinstance(head_sha, str) or not SHA.fullmatch(head_sha):
            raise ProviderFailure("artifact workflow run returned an invalid head SHA")
        if not isinstance(repository, str):
            raise ProviderFailure("artifact workflow run lacks source repository identity")
        return head_sha, repository

    def release(self, tag: str) -> dict[str, Any] | None:
        response = self.get(
            f"repos/{self.repository}/releases/tags/{quote(tag, safe='')}",
            allow_not_found=True,
        )
        if response is None:
            return None
        if not isinstance(response, dict):
            raise ProviderFailure("provider returned an invalid release")
        return response

    def releases(self) -> tuple[dict[str, Any], ...]:
        """List every release page so drafts cannot hide behind the tag endpoint."""

        response = self._run(
            [
                "api",
                "--method",
                "GET",
                "--paginate",
                "--slurp",
                f"repos/{self.repository}/releases?per_page=100",
            ]
        )
        if not isinstance(response, list):
            raise ProviderFailure("provider returned invalid paginated releases")
        releases: list[dict[str, Any]] = []
        for page in response:
            if not isinstance(page, list):
                raise ProviderFailure("provider returned an invalid releases page")
            for release in page:
                if not isinstance(release, dict):
                    raise ProviderFailure("provider returned an invalid release entry")
                releases.append(release)
        return tuple(releases)

    def create_tag(self, tag: str, target_sha: str) -> None:
        tag_object = self.post(
            f"repos/{self.repository}/git/tags",
            {
                "tag": tag,
                "message": f"Release {tag}",
                "object": target_sha,
                "type": "commit",
            },
        )
        if not isinstance(tag_object, dict):
            raise ProviderFailure("provider returned an invalid annotated tag object")
        tag_object_sha = tag_object.get("sha")
        if not isinstance(tag_object_sha, str) or not SHA.fullmatch(tag_object_sha):
            raise ProviderFailure("provider returned an invalid annotated tag SHA")
        self.post(
            f"repos/{self.repository}/git/refs",
            {"ref": f"refs/tags/{tag}", "sha": tag_object_sha},
        )

    def create_release(
        self,
        *,
        tag: str,
        target_sha: str,
        prerelease: bool,
        generate_notes: bool,
        body: str | None,
    ) -> None:
        payload: dict[str, Any] = {
            "tag_name": tag,
            "target_commitish": target_sha,
            "name": tag,
            "prerelease": prerelease,
            "generate_release_notes": generate_notes,
        }
        if body is not None:
            payload["body"] = body
        self.post(f"repos/{self.repository}/releases", payload)

    def upload(self, tag: str, asset: Path) -> None:
        result = subprocess.run(
            [
                "gh",
                "release",
                "upload",
                tag,
                str(asset),
                "--repo",
                self.repository,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            if _permission_denied(result.stderr):
                raise ContractViolation(
                    "provider token lacks permission to upload release assets"
                )
            raise ProviderFailure(
                f"provider asset upload failed ({result.returncode}): "
                f"{asset.name}{_error_detail(result.stderr)}"
            )


def _boolean(name: str, value: str) -> bool:
    normalized = value.strip().lower()
    if normalized not in {"true", "false"}:
        raise ContractViolation(f"{name} must be true or false")
    return normalized == "true"


def _validate_release_ref(value: str) -> None:
    """Reject known-invalid Git reference forms before any provider request."""

    components = value.split("/")
    if (
        not REF.fullmatch(value)
        or ".." in value
        or "//" in value
        or value.endswith(("/", ".", ".lock"))
        or any(component.startswith(".") for component in components)
    ):
        raise ContractViolation("release_ref is invalid")


def _safe_relative_file(root: Path, value: str, *, label: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ContractViolation(f"{label} must remain inside the artifact")
    resolved_root = root.resolve()
    resolved = (root / candidate).resolve()
    if resolved_root not in resolved.parents or not resolved.is_file():
        raise ContractViolation(f"{label} does not resolve to a downloaded file")
    return resolved


def _release_asset_receipts(
    release: Mapping[str, Any] | None,
) -> tuple[AssetReceipt, ...]:
    if release is None:
        return ()
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise ProviderFailure("provider release assets are not a list")
    receipts: list[AssetReceipt] = []
    for asset in assets:
        if not isinstance(asset, dict) or not isinstance(asset.get("name"), str):
            raise ProviderFailure("provider release returned an invalid asset")
        if asset.get("state") != "uploaded":
            raise ContractViolation(
                f"provider release asset is not fully uploaded: {asset['name']}"
            )
        size = asset.get("size")
        digest = asset.get("digest")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise ProviderFailure(
                f"provider release asset has invalid size: {asset['name']}"
            )
        if not isinstance(digest, str) or not ASSET_DIGEST.fullmatch(digest):
            raise ProviderFailure(
                f"provider release asset lacks a valid SHA-256 digest: {asset['name']}"
            )
        receipts.append(AssetReceipt(asset["name"], size, digest))
    return tuple(receipts)


def _local_asset_receipts(
    artifact_root: Path, expected_assets: Sequence[str]
) -> tuple[tuple[AssetReceipt, ...], dict[str, Path]]:
    receipts: list[AssetReceipt] = []
    files: dict[str, Path] = {}
    for name in expected_assets:
        path = _safe_relative_file(artifact_root, name, label=f"asset {name!r}")
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        files[name] = path
        receipts.append(
            AssetReceipt(name, path.stat().st_size, f"sha256:{digest.hexdigest()}")
        )
    return tuple(receipts), files


def _validate_artifact_members(
    artifact_root: Path,
    expected_assets: Sequence[str],
    notes_path: Path | None,
) -> None:
    resolved_root = artifact_root.resolve()
    allowed = set(expected_assets)
    if notes_path is not None:
        allowed.add(notes_path.resolve().relative_to(resolved_root).as_posix())
    unexpected: list[str] = []
    for path in artifact_root.rglob("*"):
        if not path.is_file():
            continue
        try:
            relative = path.resolve().relative_to(resolved_root).as_posix()
        except ValueError as exc:
            raise ContractViolation("artifact contains a file outside its root") from exc
        if relative not in allowed:
            unexpected.append(relative)
    unexpected.sort()
    if unexpected:
        raise ContractViolation(
            "artifact contains files outside asset_manifest: " + ", ".join(unexpected)
        )


def _assert_asset_receipts(
    provider_receipts: Sequence[AssetReceipt],
    local_receipts: Sequence[AssetReceipt],
) -> None:
    local_by_name = {receipt.name: receipt for receipt in local_receipts}
    for receipt in provider_receipts:
        if local_by_name.get(receipt.name) != receipt:
            raise ContractViolation(
                f"provider asset identity differs from trusted artifact: {receipt.name}"
            )


def _asset_receipt_json(receipts: Sequence[AssetReceipt]) -> str:
    return json.dumps(
        [
            {"name": receipt.name, "size": receipt.size, "digest": receipt.digest}
            for receipt in receipts
        ],
        sort_keys=True,
        separators=(",", ":"),
    )


def _write_outputs(values: Mapping[str, str]) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        raise ProviderFailure("GITHUB_OUTPUT is not set")
    with Path(output_path).open("a", encoding="utf-8") as output:
        for key, value in values.items():
            output.write(f"{key}={value}\n")


def run(environment: Mapping[str, str]) -> None:
    """Validate, converge when allowed, and independently read back release state."""

    repository = environment.get("RELEASE_CONTRACT_REPOSITORY", "").strip()
    version = environment.get("RELEASE_CONTRACT_VERSION", "").strip()
    supplied_tag = environment.get("RELEASE_CONTRACT_TAG", "").strip()
    tag = supplied_tag or f"v{version}"
    release_ref = environment.get("RELEASE_CONTRACT_RELEASE_REF", "").strip()
    target_sha = environment.get("RELEASE_CONTRACT_TARGET_SHA", "").strip().lower()
    tag_mode = environment.get("RELEASE_CONTRACT_TAG_MODE", "").strip()
    artifact_root = Path(
        environment.get("RELEASE_CONTRACT_ARTIFACT_DIR", "release-contract-assets")
    )
    artifact_run_id = environment.get("RELEASE_CONTRACT_ARTIFACT_RUN_ID", "").strip()
    expected_assets = parse_manifest(
        environment.get("RELEASE_CONTRACT_ASSET_MANIFEST", "")
    )
    notes_name = environment.get("RELEASE_CONTRACT_NOTES_FILE", "").strip()
    generate_notes = _boolean(
        "generate_notes", environment.get("RELEASE_CONTRACT_GENERATE_NOTES", "true")
    )
    prerelease = _boolean(
        "prerelease", environment.get("RELEASE_CONTRACT_PRERELEASE", "false")
    )
    dry_run = _boolean(
        "dry_run", environment.get("RELEASE_CONTRACT_DRY_RUN", "false")
    )

    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ContractViolation("repository must be an owner/name identifier")
    validate_version(version)
    if tag != f"v{version}":
        raise ContractViolation("tag must equal v plus version")
    _validate_release_ref(release_ref)
    if not SHA.fullmatch(target_sha):
        raise ContractViolation("target_sha must be an exact lowercase 40-character SHA")

    provider = GitHubProvider(repository)
    if provider.resolve_commit(target_sha) != target_sha:
        raise ContractViolation("target_sha did not resolve to itself at the provider")
    if artifact_run_id:
        if not re.fullmatch(r"[1-9]\d*", artifact_run_id):
            raise ContractViolation("artifact_run_id must be a positive integer")
        if artifact_run_id != environment.get("GITHUB_RUN_ID", "").strip():
            artifact_head_sha, artifact_repository = provider.artifact_run_source(
                artifact_run_id
            )
            if artifact_repository != repository or artifact_head_sha != target_sha:
                raise ContractViolation(
                    "artifact workflow run source does not match repository and target_sha"
                )
    compare_status = provider.compare_status(release_ref, target_sha)
    if compare_status not in {"behind", "identical"}:
        raise ContractViolation(
            f"target_sha is not reachable from release_ref ({compare_status})"
        )

    current_tag_sha = provider.tag_sha(tag)
    release = provider.release(tag)
    matching_drafts = tuple(
        candidate
        for candidate in provider.releases()
        if candidate.get("tag_name") == tag and bool(candidate.get("draft"))
    )
    if matching_drafts:
        raise ContractViolation("a draft already owns the contract tag")
    if release is not None and bool(release.get("prerelease")) != prerelease:
        raise ContractViolation("existing release prerelease state differs from input")
    current_asset_receipts = _release_asset_receipts(release)
    decision = decide(
        tag_sha=current_tag_sha,
        target_sha=target_sha,
        tag_mode=tag_mode,
        release_exists=release is not None,
        existing_assets=tuple(receipt.name for receipt in current_asset_receipts),
        expected_assets=expected_assets,
    )

    notes_path = (
        _safe_relative_file(artifact_root, notes_name, label="notes_file")
        if notes_name
        else None
    )
    local_asset_receipts, all_asset_files = _local_asset_receipts(
        artifact_root, expected_assets
    )
    _validate_artifact_members(artifact_root, expected_assets, notes_path)
    _assert_asset_receipts(current_asset_receipts, local_asset_receipts)
    asset_files = {name: all_asset_files[name] for name in decision.missing_assets}

    if dry_run:
        _write_outputs(
            {
                "tag": tag,
                "version": version,
                "target_sha": target_sha,
                "release_id": "" if release is None else str(release.get("id", "")),
                "release_url": ""
                if release is None
                else str(release.get("html_url", "")),
                "created": "false",
                "repaired": "false",
                "assets_uploaded": "0",
                "assets_receipt": _asset_receipt_json(current_asset_receipts),
            }
        )
        return

    if decision.create_tag:
        provider.create_tag(tag, target_sha)
    if decision.create_release:
        provider.create_release(
            tag=tag,
            target_sha=target_sha,
            prerelease=prerelease,
            generate_notes=generate_notes and notes_path is None,
            body=None if notes_path is None else notes_path.read_text(encoding="utf-8"),
        )
    for name in decision.missing_assets:
        provider.upload(tag, asset_files[name])

    final_tag_sha = provider.tag_sha(tag)
    final_release = provider.release(tag)
    if final_tag_sha != target_sha:
        raise ProviderFailure("tag readback does not match target_sha")
    if final_release is None:
        raise ProviderFailure("release readback is absent after convergence")
    if final_release.get("tag_name") != tag:
        raise ProviderFailure("release readback tag does not match the contract tag")
    if bool(final_release.get("draft")):
        raise ProviderFailure("release readback is still a draft")
    if bool(final_release.get("prerelease")) != prerelease:
        raise ProviderFailure("release readback prerelease state does not match input")
    if not final_release.get("id") or not final_release.get("html_url"):
        raise ProviderFailure("release readback lacks provider identity")
    final_asset_receipts = _release_asset_receipts(final_release)
    final_assets = tuple(receipt.name for receipt in final_asset_receipts)
    if set(final_assets) != set(expected_assets) or len(final_assets) != len(
        expected_assets
    ):
        raise ProviderFailure("release asset readback does not match asset_manifest")
    _assert_asset_receipts(final_asset_receipts, local_asset_receipts)

    _write_outputs(
        {
            "tag": tag,
            "version": version,
            "target_sha": target_sha,
            "release_id": str(final_release.get("id", "")),
            "release_url": str(final_release.get("html_url", "")),
            "created": str(decision.create_release).lower(),
            "repaired": str(
                not decision.create_release and bool(decision.missing_assets)
            ).lower(),
            "assets_uploaded": str(len(decision.missing_assets)),
            "assets_receipt": _asset_receipt_json(final_asset_receipts),
        }
    )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = tuple(sys.argv[1:] if argv is None else argv)
    try:
        if arguments:
            if len(arguments) != 2 or arguments[0] not in {
                "--validate-version",
                "--validate-stable-version",
            }:
                raise ContractViolation("unsupported release-contract arguments")
            if arguments[0] == "--validate-stable-version":
                validate_stable_version(arguments[1])
            else:
                validate_version(arguments[1])
        else:
            run(os.environ)
    except ContractViolation as exc:
        print(f"::error::CONTRACT_VIOLATION: {exc}", file=sys.stderr)
        return 2
    except ProviderFailure as exc:
        print(f"::error::PROVIDER_FAILURE: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
