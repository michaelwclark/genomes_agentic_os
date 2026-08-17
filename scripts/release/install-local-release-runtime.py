#!/usr/bin/env python3
"""Install one released wheel into the rollback-safe macOS local runtime.

The installer builds a non-editable, versioned virtual environment and only
switches the dispatcher aliases after package and CLI readback succeeds.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from email.parser import Parser
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import IO, NamedTuple
import uuid
import zipfile

try:
    from packaging.markers import default_environment
    from packaging.requirements import InvalidRequirement, Requirement
except ModuleNotFoundError:  # pragma: no cover - release hosts may expose only pip's vendor
    from pip._vendor.packaging.markers import default_environment
    from pip._vendor.packaging.requirements import InvalidRequirement, Requirement


PACKAGE = "genomes-agentic-os"
MODULE = "genomes_agentic_os"
# The top-level dispatcher falls back to agentic-os-source. Keep that fallback
# on the same validated release as the Auto-Dev aliases so review coordination
# cannot be present on only one dispatch path; alias activation retains the
# existing previous links for rollback.
ALIASES = ("development-delivery-runtime", "layout-v2-runtime", "agentic-os-source")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REVISION = re.compile(r"^[0-9a-fA-F]{7,40}$")


class AliasActivation(NamedTuple):
    aliases: list[dict[str, object]]
    active_snapshots: dict[Path, dict[str, str | None]]
    previous_snapshots: dict[Path, dict[str, str | None]]


class ReviewRolloutGuard(NamedTuple):
    handles: list[IO[str]]
    evidence: dict[str, object]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def wheel_metadata(path: Path) -> tuple[str, str, list[str]]:
    if not path.is_file() or path.suffix != ".whl":
        raise ValueError(f"release wheel is missing or not a .whl file: {path}")
    with zipfile.ZipFile(path) as archive:
        metadata_files = [
            name
            for name in archive.namelist()
            if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_files) != 1:
            raise ValueError("wheel must contain exactly one dist-info/METADATA file")
        metadata = Parser().parsestr(
            archive.read(metadata_files[0]).decode("utf-8")
        )
    name = metadata.get("Name", "").strip().lower().replace("_", "-")
    version = metadata.get("Version", "").strip()
    if name != PACKAGE or not version:
        raise ValueError(
            f"expected {PACKAGE} wheel metadata, found name={name!r} version={version!r}"
        )
    return name, version, metadata.get_all("Requires-Dist", [])


def applicable_runtime_requirements(
    raw_requirements: list[str], marker_environment: dict[str, str]
) -> list[str]:
    environment = dict(marker_environment)
    environment["extra"] = ""
    requirements: list[str] = []
    for raw_requirement in raw_requirements:
        try:
            requirement = Requirement(raw_requirement)
        except InvalidRequirement as error:
            raise ValueError(
                f"wheel contains invalid Requires-Dist metadata: {raw_requirement!r}"
            ) from error
        if requirement.marker is None or requirement.marker.evaluate(environment):
            requirements.append(str(requirement))
    return requirements


def wheel_identity(
    path: Path, marker_environment: dict[str, str] | None = None
) -> tuple[str, str, list[str]]:
    name, version, raw_requirements = wheel_metadata(path)
    environment = marker_environment or default_environment()
    return (
        name,
        version,
        applicable_runtime_requirements(raw_requirements, environment),
    )


def target_marker_environment(python: str) -> dict[str, str]:
    code = """
import json
import os
import platform
import sys

version = sys.implementation.version
implementation_version = f"{version.major}.{version.minor}.{version.micro}"
if version.releaselevel != "final":
    implementation_version += version.releaselevel[0] + str(version.serial)
print(json.dumps({
    "implementation_name": sys.implementation.name,
    "implementation_version": implementation_version,
    "os_name": os.name,
    "platform_machine": platform.machine(),
    "platform_release": platform.release(),
    "platform_system": platform.system(),
    "platform_version": platform.version(),
    "python_full_version": platform.python_version(),
    "platform_python_implementation": platform.python_implementation(),
    "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
    "sys_platform": sys.platform,
}))
"""
    result = _run([python, "-c", code])
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ValueError("target interpreter returned invalid marker environment") from error
    if not isinstance(value, dict) or any(
        not isinstance(key, str) or not isinstance(item, str)
        for key, item in value.items()
    ):
        raise ValueError("target interpreter marker environment must contain strings")
    required = set(default_environment())
    if not required.issubset(value):
        missing = ", ".join(sorted(required - set(value)))
        raise ValueError(f"target interpreter marker environment is missing: {missing}")
    return value


def _normalized_revision(
    value: object, *, label: str, require_full: bool = False
) -> str:
    if not isinstance(value, str) or not REVISION.fullmatch(value):
        raise ValueError(f"{label} must be a 7-40 character hexadecimal Git revision")
    if require_full and len(value) != 40:
        raise ValueError(f"{label} must record the full 40-character Git revision")
    return value.lower()


def _same_revision(left: str, right: str) -> bool:
    return left.startswith(right) or right.startswith(left)


def review_rollout_proof(path: Path, *, release_revision: str) -> dict[str, object]:
    if not path.is_file():
        raise ValueError(f"review rollout receipt does not exist: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"review rollout receipt is not valid JSON: {path}") from error
    if not isinstance(value, dict):
        raise ValueError("review rollout receipt must be a JSON object")
    if value.get("schema_version") != "review-coordination-rollout/v1":
        raise ValueError(
            "review rollout receipt requires "
            "schema_version='review-coordination-rollout/v1'"
        )
    expected_revision = _normalized_revision(
        release_revision, label="--release-revision"
    )
    receipt_revision = _normalized_revision(
        value.get("release_revision"),
        label="review rollout release_revision",
        require_full=True,
    )
    if not _same_revision(expected_revision, receipt_revision):
        raise ValueError(
            "review rollout release_revision does not identify the requested revision"
        )
    if value.get("quiesced") is not True:
        raise ValueError("review rollout receipt requires quiesced=true")
    active_reviews = value.get("active_reviews")
    if type(active_reviews) is not int or active_reviews != 0:
        raise ValueError("review rollout receipt requires integer active_reviews=0")
    if value.get("migration_verified") is not True:
        raise ValueError("review rollout receipt requires migration_verified=true")
    if value.get("budget_history_preserved") is not True:
        raise ValueError("review rollout receipt requires budget_history_preserved=true")
    strategy = value.get("receipt_strategy")
    if strategy not in {"migrated", "shared-existing"}:
        raise ValueError(
            "review rollout receipt strategy must be migrated or shared-existing"
        )
    target_value = value.get("target_receipt_root")
    sources = value.get("source_receipt_roots")
    if (
        not isinstance(target_value, str)
        or not isinstance(sources, list)
        or not sources
        or any(not isinstance(item, str) for item in sources)
    ):
        raise ValueError(
            "review rollout receipt requires one absolute target and source roots"
        )
    target = Path(target_value).expanduser()
    source_paths = [Path(item).expanduser() for item in sources]
    if not target.is_absolute() or any(not item.is_absolute() for item in source_paths):
        raise ValueError("review rollout source roots must be absolute")
    if strategy == "shared-existing" and any(item != target for item in source_paths):
        raise ValueError(
            "shared-existing rollout requires every source root to equal target root"
        )
    expires_at = value.get("expires_at")
    if not isinstance(expires_at, str):
        raise ValueError("review rollout receipt requires an ISO-8601 expires_at")
    try:
        expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("review rollout receipt requires an ISO-8601 expires_at") from error
    if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
        raise ValueError("review rollout receipt is expired")
    return value


def _receipt_inventory(root: Path) -> dict[str, str]:
    receipt_dir = root / "receipts"
    if not root.exists():
        raise ValueError(f"review coordination root does not exist: {root}")
    if not root.is_dir():
        raise ValueError(f"review coordination root is not a directory: {root}")
    if not receipt_dir.exists():
        return {}
    if not receipt_dir.is_dir():
        raise ValueError(f"review coordination receipts path is not a directory: {receipt_dir}")
    inventory: dict[str, str] = {}
    for receipt_path in sorted(receipt_dir.glob("*.json")):
        try:
            payload = json.loads(receipt_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid review receipt JSON: {receipt_path}") from error
        if not isinstance(payload, dict):
            raise ValueError(f"review receipt must be an object: {receipt_path}")
        if payload.get("schema") != "auto-dev-review-receipt/v1":
            raise ValueError(f"review receipt schema is invalid: {receipt_path}")
        if payload.get("status") != "completed" or payload.get("outcome") not in {
            "clean",
            "findings",
        }:
            raise ValueError(f"review receipt is not budget-consuming terminal evidence: {receipt_path}")
        if payload.get("key") != receipt_path.stem:
            raise ValueError(f"review receipt filename does not match its key: {receipt_path}")
        inventory[receipt_path.name] = sha256(receipt_path)
    return inventory


def acquire_review_rollout_guard(proof: dict[str, object]) -> ReviewRolloutGuard:
    target = Path(str(proof["target_receipt_root"])).expanduser().resolve()
    sources = [
        Path(str(item)).expanduser().resolve()
        for item in proof["source_receipt_roots"]  # type: ignore[union-attr]
    ]
    roots = sorted({*sources, target}, key=str)
    handles: list[IO[str]] = []
    lock_count = 0
    probed_lock_names: list[str] = []
    busy_lock_names: list[str] = []
    scanned_at = datetime.now(timezone.utc).isoformat()
    try:
        for root in roots:
            lock_dir = root / ".locks"
            if not root.exists():
                raise ValueError(f"review coordination root does not exist: {root}")
            if not root.is_dir():
                raise ValueError(f"review coordination root is not a directory: {root}")
            if not lock_dir.exists():
                continue
            if not lock_dir.is_dir():
                raise ValueError(
                    f"review coordination locks path is not a directory: {lock_dir}"
                )
            for lock_path in sorted(lock_dir.glob("*.lock")):
                qualified_name = f"{root}:{lock_path.name}"
                probed_lock_names.append(qualified_name)
                handle = lock_path.open("a+", encoding="utf-8")
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as error:
                    busy_lock_names.append(qualified_name)
                    handle.close()
                    raise ValueError(
                        f"review coordination is not drained; live family lock: {lock_path}"
                    ) from error
                handles.append(handle)
                lock_count += 1

        target_inventory = _receipt_inventory(target)
        source_inventories = {str(root): _receipt_inventory(root) for root in sources}
        required_inventory: dict[str, str] = {}
        for root, inventory in source_inventories.items():
            for name, digest in inventory.items():
                prior = required_inventory.get(name)
                if prior is not None and prior != digest:
                    raise ValueError(
                        f"review receipt collision differs across source roots: {name}"
                    )
                required_inventory[name] = digest
                if target_inventory.get(name) != digest:
                    raise ValueError(
                        f"review receipt budget history is missing or changed at target: {name}"
                    )
        evidence: dict[str, object] = {
            "lock_probe_started_at": scanned_at,
            "active_review_measurement": "nonblocking-family-lock-probe",
            "observed_active_reviews": len(busy_lock_names),
            "probed_family_locks": probed_lock_names,
            "held_family_locks": lock_count,
            "source_receipt_counts": {
                root: len(inventory) for root, inventory in source_inventories.items()
            },
            "required_receipt_count": len(required_inventory),
            "target_receipt_count": len(target_inventory),
            "receipt_digests_matched": len(required_inventory),
        }
        return ReviewRolloutGuard(handles, evidence)
    except Exception:
        for handle in reversed(handles):
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
        raise


def release_review_rollout_guard(guard: ReviewRolloutGuard) -> None:
    for handle in reversed(guard.handles):
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def expected_sha256(
    wheel: Path,
    *,
    value: str | None,
    checksum_file: Path | None,
) -> str | None:
    if value:
        normalized = value.lower().removeprefix("sha256:")
        if not SHA256.fullmatch(normalized):
            raise ValueError("--sha256 must be exactly 64 hexadecimal characters")
        return normalized
    if checksum_file is None:
        return None
    if not checksum_file.is_file():
        raise ValueError(f"checksum file does not exist: {checksum_file}")
    candidates: list[tuple[str, str | None]] = []
    for raw_line in checksum_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        digest = fields[0].lower().removeprefix("sha256:")
        if not SHA256.fullmatch(digest):
            continue
        filename = fields[-1].removeprefix("*") if len(fields) > 1 else None
        if filename == f"./{wheel.name}":
            filename = wheel.name
        elif filename != wheel.name:
            # Never resolve paths: manifest matching is a parser decision, not
            # a filesystem lookup. Only the exact basename or POSIX ./ form is legal.
            filename = None
        candidates.append((digest, filename))
    named = [digest for digest, name in candidates if name == wheel.name]
    if len(named) == 1:
        return named[0]
    raise ValueError(
        f"checksum file must contain one unambiguous entry for {wheel.name}"
    )


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )


def _link_snapshot(path: Path) -> dict[str, str | None]:
    if not os.path.lexists(path):
        return {"raw": None, "resolved": None}
    if not path.is_symlink():
        raise ValueError(f"refusing to replace non-symlink runtime path: {path}")
    raw = os.readlink(path)
    raw_path = Path(raw)
    resolved = raw_path if raw_path.is_absolute() else path.parent / raw_path
    return {"raw": raw, "resolved": str(resolved.resolve(strict=False))}


def _replace_symlink(path: Path, target: str | Path) -> None:
    temporary = path.with_name(f".{path.name}.swap-{uuid.uuid4().hex}")
    os.symlink(str(target), temporary)
    try:
        os.replace(temporary, path)
    finally:
        if os.path.lexists(temporary):
            temporary.unlink()


def _restore_symlink(path: Path, snapshot: dict[str, str | None]) -> None:
    raw = snapshot["raw"]
    if raw is None:
        if os.path.lexists(path):
            path.unlink()
        return
    _replace_symlink(path, raw)


def _require_consistent_pair(
    snapshots: dict[Path, dict[str, str | None]], *, label: str
) -> str | None:
    targets = {snapshot["resolved"] for snapshot in snapshots.values()}
    if len(targets) != 1:
        rendered = ", ".join(
            f"{path.name}={snapshot['resolved']!r}"
            for path, snapshot in snapshots.items()
        )
        raise ValueError(f"{label} aliases are inconsistent: {rendered}")
    target = next(iter(targets))
    if target is not None and not Path(target).exists():
        raise ValueError(f"{label} alias target does not exist: {target}")
    return target


def _restore_alias_activation(activation: AliasActivation) -> None:
    for path, snapshot in activation.active_snapshots.items():
        _restore_symlink(path, snapshot)
    for path, snapshot in activation.previous_snapshots.items():
        _restore_symlink(path, snapshot)


def activate_aliases(runtime_root: Path, target: Path) -> AliasActivation:
    aliases = [runtime_root / name for name in ALIASES]
    snapshots = {alias: _link_snapshot(alias) for alias in aliases}
    prior_target = _require_consistent_pair(snapshots, label="active runtime")
    previous_paths = {alias: alias.with_name(f"{alias.name}.previous") for alias in aliases}
    previous_snapshots = {
        previous_paths[alias]: _link_snapshot(previous_paths[alias]) for alias in aliases
    }
    activation = AliasActivation([], snapshots, previous_snapshots)
    try:
        for alias in aliases:
            if prior_target is not None:
                _replace_symlink(previous_paths[alias], prior_target)
            elif os.path.lexists(previous_paths[alias]):
                previous_paths[alias].unlink()
        for alias in aliases:
            _replace_symlink(alias, target)

        active_readback = {alias: _link_snapshot(alias) for alias in aliases}
        activated_target = _require_consistent_pair(
            active_readback, label="activated runtime"
        )
        expected_target = str(target.resolve(strict=True))
        if activated_target != expected_target:
            raise ValueError(
                f"activated alias readback mismatch: expected {expected_target}, "
                f"got {activated_target}"
            )

        rollback_readback = {
            alias: _link_snapshot(previous_paths[alias]) for alias in aliases
        }
        rollback_target = _require_consistent_pair(
            rollback_readback, label="rollback"
        )
        if rollback_target != prior_target:
            raise ValueError(
                f"rollback pointer readback mismatch: expected {prior_target}, "
                f"got {rollback_target}"
            )
    except Exception:
        _restore_alias_activation(activation)
        raise

    entries = [
        {
            "alias": str(alias),
            "prior_target": snapshots[alias]["resolved"],
            "new_target": str(target),
            "readback_target": str(alias.resolve(strict=True)),
            "rollback_pointer": str(previous_paths[alias]),
            "rollback_target": (
                str(previous_paths[alias].resolve(strict=True))
                if previous_paths[alias].exists()
                else None
            ),
        }
        for alias in aliases
    ]
    return AliasActivation(entries, snapshots, previous_snapshots)


def _readback(target: Path, version: str) -> dict[str, object]:
    python = target / "bin" / "python"
    cli = target / "bin" / "agentic-os"
    code = (
        "import importlib, importlib.metadata, json, pathlib; "
        f"m=importlib.import_module('{MODULE}'); "
        f"print(json.dumps({{'package':'{PACKAGE}',"
        f"'version':importlib.metadata.version('{PACKAGE}'),"
        "'module_path':str(pathlib.Path(m.__file__).resolve())}))"
    )
    package_result = _run([str(python), "-c", code])
    package = json.loads(package_result.stdout)
    if package.get("version") != version:
        raise ValueError(
            f"installed version mismatch: expected {version}, got {package.get('version')}"
        )
    module_path = Path(str(package.get("module_path", ""))).resolve(strict=False)
    if target.resolve(strict=False) not in module_path.parents:
        raise ValueError(f"installed module escaped the versioned runtime: {module_path}")
    smoke = _run([str(cli), "--help"])
    return {
        "package": package,
        "smoke": {
            "command": [str(cli), "--help"],
            "exit_code": smoke.returncode,
            "stdout_nonempty": bool(smoke.stdout.strip()),
        },
    }


def _write_json_atomic(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def install(arguments: argparse.Namespace) -> dict[str, object]:
    wheel = arguments.wheel.expanduser().resolve(strict=False)
    runtime_root = arguments.runtime_root.expanduser().resolve(strict=False)
    receipt_path = arguments.receipt.expanduser().resolve(strict=False)
    package_name, version, raw_requirements = wheel_metadata(wheel)
    if not REVISION.fullmatch(arguments.release_revision):
        raise ValueError("--release-revision must be a 7-40 character Git SHA")
    expected = expected_sha256(
        wheel,
        value=arguments.sha256,
        checksum_file=arguments.sha256_file,
    )
    if expected is None and not arguments.allow_unverified:
        raise ValueError(
            "a trusted --sha256 or --sha256-file is required; "
            "use --allow-unverified only for an explicit non-release recovery"
        )
    actual = sha256(wheel)
    if expected is not None and actual != expected:
        raise ValueError(f"wheel SHA-256 mismatch: expected {expected}, got {actual}")

    dependency_lock_arg = getattr(arguments, "dependency_lock", None)
    wheelhouse_arg = getattr(arguments, "wheelhouse", None)
    if (dependency_lock_arg is None) != (wheelhouse_arg is None):
        raise ValueError("--dependency-lock and --wheelhouse must be supplied together")
    dependency_lock = (
        dependency_lock_arg.expanduser().resolve(strict=False)
        if dependency_lock_arg is not None
        else None
    )
    wheelhouse = (
        wheelhouse_arg.expanduser().resolve(strict=False)
        if wheelhouse_arg is not None
        else None
    )
    if dependency_lock is not None and not dependency_lock.is_file():
        raise ValueError(f"dependency lock does not exist: {dependency_lock}")
    if wheelhouse is not None and not wheelhouse.is_dir():
        raise ValueError(f"dependency wheelhouse does not exist: {wheelhouse}")
    release_dir = runtime_root / "releases" / f"{version}-{arguments.release_revision[:7].lower()}"
    target = release_dir / "runtime"
    if os.path.lexists(target):
        raise ValueError(f"versioned runtime already exists; refusing to overwrite: {target}")
    initial_aliases = {
        runtime_root / alias_name: _link_snapshot(runtime_root / alias_name)
        for alias_name in ALIASES
    }
    prior_runtime = _require_consistent_pair(initial_aliases, label="active runtime")
    rollout_path_arg = getattr(arguments, "review_rollout_receipt", None)
    rollout_path = (
        rollout_path_arg.expanduser().resolve(strict=False)
        if rollout_path_arg is not None
        else None
    )
    rollout: dict[str, object] | None = None
    rollout_guard: ReviewRolloutGuard | None = None
    if prior_runtime is not None:
        if rollout_path is None:
            raise ValueError(
                "runtime upgrade requires --review-rollout-receipt proving drain, "
                "receipt migration/shared root, and preserved budgets"
            )
        rollout = review_rollout_proof(
            rollout_path, release_revision=arguments.release_revision
        )
        rollout_guard = acquire_review_rollout_guard(rollout)

    created = False
    activation: AliasActivation | None = None
    marker_environment: dict[str, str] | None = None
    runtime_requirements: list[str] = []
    try:
        marker_environment = target_marker_environment(arguments.python)
        runtime_requirements = applicable_runtime_requirements(
            raw_requirements, marker_environment
        )
        if runtime_requirements and dependency_lock is None:
            raise ValueError(
                "wheel declares runtime dependencies; --dependency-lock and "
                "--wheelhouse are required: " + ", ".join(runtime_requirements)
            )
        runtime_root.mkdir(parents=True, exist_ok=True)
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        release_dir.mkdir(parents=True, exist_ok=False)
        created = True
        _run([arguments.python, "-m", "venv", str(target)])
        if dependency_lock is not None and wheelhouse is not None:
            _run(
                [
                    str(target / "bin" / "python"),
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "--no-index",
                    "--find-links",
                    str(wheelhouse),
                    "--require-hashes",
                    "--no-deps",
                    "-r",
                    str(dependency_lock),
                ]
            )
        _run(
            [
                str(target / "bin" / "python"),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-deps",
                str(wheel),
            ]
        )
        dependency_check = _run(
            [str(target / "bin" / "python"), "-m", "pip", "check"]
        )
        validation = _readback(target, version)
        activation = activate_aliases(runtime_root, target)
        aliases = activation.aliases
        receipt: dict[str, object] = {
            "schema_version": "local-release-runtime-install/v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "package": {
                "name": package_name,
                "version": version,
                "module": MODULE,
                "module_path": validation["package"]["module_path"],
            },
            "release_revision": arguments.release_revision.lower(),
            "wheel": {
                "path": str(wheel),
                "sha256": actual,
                "expected_sha256": expected,
                "checksum_verified": expected is not None,
                "requires_dist": runtime_requirements,
            },
            "runtime": {
                "root": str(runtime_root),
                "target": str(target),
                "editable": False,
            },
            "dependencies": {
                "mode": "hash-pinned-wheelhouse" if dependency_lock else "none",
                "lock": str(dependency_lock) if dependency_lock else None,
                "lock_sha256": sha256(dependency_lock) if dependency_lock else None,
                "wheelhouse": str(wheelhouse) if wheelhouse else None,
                "network_disabled": True,
                "dependency_resolution_disabled": True,
                "marker_environment": marker_environment,
                "pip_check": {
                    "command": [str(target / "bin" / "python"), "-m", "pip", "check"],
                    "exit_code": dependency_check.returncode,
                    "stdout": dependency_check.stdout.strip(),
                },
            },
            "review_coordination_rollout": {
                "required": prior_runtime is not None,
                "receipt": str(rollout_path) if rollout_path else None,
                "receipt_sha256": sha256(rollout_path) if rollout_path else None,
                "proof": rollout,
                "verified_evidence": rollout_guard.evidence if rollout_guard else None,
            },
            "aliases": aliases,
            "smoke": validation["smoke"],
            "readback_verified": True,
            "rollback_retained": all(
                entry["prior_target"] is None or entry["rollback_target"] == entry["prior_target"]
                for entry in aliases
            ),
            "rollback_available": aliases[0]["prior_target"] is not None,
        }
        if not receipt["rollback_retained"]:
            raise ValueError("rollback pointer retention failed")
        _write_json_atomic(receipt_path, receipt)
        return receipt
    except Exception:
        if activation is not None:
            _restore_alias_activation(activation)
        if created and release_dir.exists():
            shutil.rmtree(release_dir)
        raise
    finally:
        if rollout_guard is not None:
            release_review_rollout_guard(rollout_guard)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--release-revision", required=True)
    parser.add_argument(
        "--runtime-root",
        type=Path,
        default=Path.home() / "Library/Application Support/AgenticOS",
    )
    parser.add_argument("--receipt", type=Path, required=True)
    checksum = parser.add_mutually_exclusive_group()
    checksum.add_argument("--sha256")
    checksum.add_argument("--sha256-file", type=Path)
    parser.add_argument("--allow-unverified", action="store_true")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument(
        "--dependency-lock",
        type=Path,
        help="complete requirements file with hashes for the dependency closure",
    )
    parser.add_argument(
        "--wheelhouse",
        type=Path,
        help="offline wheel directory used with --dependency-lock",
    )
    parser.add_argument(
        "--review-rollout-receipt",
        type=Path,
        help=(
            "short-lived drain and receipt-migration proof required when replacing "
            "an existing runtime"
        ),
    )
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args(argv)
    if not arguments.apply:
        parser.error("installation mutates runtime aliases; pass --apply")
    return arguments


def main(argv: list[str] | None = None) -> int:
    arguments = parse_args(argv)
    try:
        receipt = install(arguments)
    except (OSError, ValueError, subprocess.CalledProcessError, zipfile.BadZipFile) as error:
        raise SystemExit(f"local release runtime install failed: {error}") from error
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
