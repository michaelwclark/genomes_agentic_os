from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


SOURCE_ROOT = Path(__file__).resolve().parents[1]
BACKUP = SOURCE_ROOT / "deploy/execution-fabric/scripts/postgres-backup.sh"
VALIDATOR = (
    SOURCE_ROOT
    / "installers/execution-fabric/bin/validate-backup-health-receipt.sh"
)
GENERATOR = SOURCE_ROOT / "installers/execution-fabric/bin/backup-health.sh"
BACKUP_SERVICE = (
    SOURCE_ROOT
    / "deploy/execution-fabric/systemd/"
    "genomes-agentic-os-execution-fabric-backup.service"
)


def test_backup_performs_real_disposable_restore_and_readback() -> None:
    script = BACKUP.read_text(encoding="utf-8")
    assert "createdb --template=template0" in script
    assert "pg_restore --exit-on-error" in script
    assert '--dbname="$restore_database"' in script
    assert "ROWCOUNT|" in script
    assert 'dropdb "$restore_database"' in script
    assert "restoreDatabaseDropped" in script
    assert script.index("pg_restore --exit-on-error") < script.index(
        "restoreManifestVerified"
    )
    assert script.index('dropdb "$restore_database"') < script.index(
        '"status":"passed"'
    )


def test_shipped_timer_path_generates_and_validates_the_same_run_receipt() -> None:
    generator = GENERATOR.read_text(encoding="utf-8")
    service = BACKUP_SERVICE.read_text(encoding="utf-8")
    assert GENERATOR.stat().st_mode & 0o111
    assert "backup-health.sh" in service
    assert "--profile backup run --rm" in generator
    assert "validate-backup-health-receipt.sh" in generator
    assert "backup receipt does not belong to this backup run" in generator


def _receipt_fixture(tmp_path: Path) -> tuple[Path, Path]:
    state = tmp_path / "state"
    state.mkdir()
    manifest = state / "backup-health.restore-manifest.json"
    backup_sha = "a" * 64
    manifest.write_text(
        json.dumps(
            {
                "schemaVersion": "execution-fabric-postgres-restore-manifest/v1",
                "runId": "backup-test",
                "backupFile": "execution_fabric.dump",
                "backupSha256": backup_sha,
                "backupBytes": 42,
                "archiveManifestSha256": "b" * 64,
                "archiveEntryCount": 1,
                "readbackManifestSha256": "c" * 64,
                "readbackLineCount": 1,
                "tableCount": 0,
                "restoreDatabaseCreated": True,
                "restoreCompleted": True,
                "readbackCompleted": True,
                "restoreDatabaseDropped": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    manifest_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
    receipt = state / "backup-health.json"
    receipt.write_text(
        json.dumps(
            {
                "schemaVersion": "execution-fabric-backup-health/v1",
                "status": "passed",
                "runId": "backup-test",
                "verifiedAt": subprocess.check_output(
                    ["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"], text=True
                ).strip(),
                "backupFile": "execution_fabric.dump",
                "backupSha256": backup_sha,
                "restoreManifestVerified": True,
                "restoreManifest": {
                    "schemaVersion": "execution-fabric-postgres-restore-manifest/v1",
                    "file": manifest.name,
                    "sha256": manifest_sha,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    runtime = tmp_path / "runtime.env"
    runtime.write_text(
        "\n".join(
            [
                f"FABRIC_OS_ROOT={tmp_path}",
                f"FABRIC_RUNTIME_STATE_DIR={state}",
                f"FABRIC_BACKUP_HEALTH_RECEIPT_FILE={receipt}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return receipt, runtime


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq is required")
def test_validator_accepts_hash_bound_restore_manifest_and_rejects_tampering(
    tmp_path: Path,
) -> None:
    receipt, runtime = _receipt_fixture(tmp_path)
    env = {**os.environ, "FABRIC_RUNTIME_ENV_FILE": str(runtime)}
    passed = subprocess.run([str(VALIDATOR)], env=env, text=True, capture_output=True)
    assert passed.returncode == 0, passed.stderr

    manifest = receipt.parent / "backup-health.restore-manifest.json"
    manifest.write_text(manifest.read_text(encoding="utf-8") + " ", encoding="utf-8")
    failed = subprocess.run([str(VALIDATOR)], env=env, text=True, capture_output=True)
    assert failed.returncode == 75
    assert "hash does not match" in failed.stderr
