from __future__ import annotations

import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

import jsonschema
import yaml


SOURCE_ROOT = Path(__file__).resolve().parents[1]
DEPLOY = SOURCE_ROOT / "deploy" / "execution-fabric"
INSTALLERS = SOURCE_ROOT / "installers" / "execution-fabric"


def _yaml(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _all_text(root: Path) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )


def _write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_deployment_assets_are_discoverable_from_one_focused_root() -> None:
    assert (DEPLOY / "README.md").is_file()
    assert (INSTALLERS / "README.md").is_file()
    assert (DEPLOY / "compose.genomesbox.yml").is_file()
    assert (DEPLOY / "compose.bigmac.yml").is_file()
    manifest = _yaml(DEPLOY / "emergency-bundle" / "manifest.yml")
    assert manifest["id"] == "execution-fabric-emergency-bundle"
    assert "deploy/execution-fabric/helm/los-agents" in manifest["required_assets"]
    assert "deploy/execution-fabric/witness" in manifest["required_assets"]
    assert "installers/execution-fabric" in manifest["required_assets"]
    installer_manifest = _yaml(INSTALLERS / "manifest.yml")
    assert installer_manifest["canonical_instance_config"] == (
        "harness/config/execution-fabric.yml"
    )
    assert set(installer_manifest["platforms"]) == {
        "linux",
        "macos",
        "kubernetes",
        "aws_witness",
    }
    assert installer_manifest["platforms"]["linux"]["activator"].endswith(
        "activate-linux.sh"
    )
    assert installer_manifest["platforms"]["macos"]["activator"].endswith(
        "activate-macos.sh"
    )
    assert installer_manifest["runtime_contract"]["host_worker_executable"].endswith(
        "bin/python-worker.sh"
    )


def test_emergency_bundle_manifest_matches_schema() -> None:
    manifest = _yaml(DEPLOY / "emergency-bundle" / "manifest.yml")
    schema = json.loads(
        (DEPLOY / "emergency-bundle" / "manifest.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.validate(manifest, schema)
    assert manifest["recovery"]["witness_required"] is True
    assert manifest["recovery"]["epoch_advance_required"] is True
    assert manifest["recovery"]["failback_mode"] == "manual"


def test_compose_images_are_required_external_immutable_lock_variables() -> None:
    for name in ("compose.genomesbox.yml", "compose.bigmac.yml"):
        compose = _yaml(DEPLOY / name)
        for service in compose["services"].values():
            image = service["image"]
            assert image.startswith("${FABRIC_")
            assert ":?" in image
            assert ":latest" not in image
    assert ":latest" not in _all_text(DEPLOY)


def test_all_published_compose_ports_bind_only_to_explicit_tailscale_ip() -> None:
    for name in ("compose.genomesbox.yml", "compose.bigmac.yml"):
        compose = _yaml(DEPLOY / name)
        for service in compose["services"].values():
            for port in service.get("ports", []):
                assert port.startswith(
                    "${FABRIC_TAILSCALE_IP:?"
                ), f"{name}:{service} publishes a non-Tailscale port: {port}"
        assert compose["networks"]["fabric-private"]["internal"] is True


def test_postgres_replication_host_port_is_configurable_and_non_conflicting() -> None:
    expected = (
        "${FABRIC_TAILSCALE_IP:?set the genomesbox Tailscale IP}:"
        "${FABRIC_POSTGRES_REPLICATION_PORT:-35432}:5432"
    )
    primary = _yaml(DEPLOY / "compose.genomesbox.yml")
    standby = _yaml(DEPLOY / "compose.bigmac.yml")
    assert primary["services"]["postgres"]["ports"] == [expected]
    assert standby["services"]["postgres"]["ports"] == [
        expected.replace("genomesbox", "bigmac")
    ]
    standby_environment = standby["services"]["postgres"]["environment"]
    assert standby_environment["FABRIC_POSTGRES_REPLICATION_PORT"] == (
        "${FABRIC_POSTGRES_REPLICATION_PORT:-35432}"
    )
    entrypoint = (
        DEPLOY / "scripts" / "postgres-standby-entrypoint.sh"
    ).read_text(encoding="utf-8")
    assert '--port="${FABRIC_POSTGRES_REPLICATION_PORT:-35432}"' in entrypoint
    runtime_env = (DEPLOY / "runtime.env.example").read_text(encoding="utf-8")
    assert "FABRIC_POSTGRES_REPLICATION_PORT=35432" in runtime_env


def test_long_running_services_have_healthchecks_and_durable_volumes() -> None:
    primary = _yaml(DEPLOY / "compose.genomesbox.yml")
    standby = _yaml(DEPLOY / "compose.bigmac.yml")
    for compose in (primary, standby):
        for service_name in ("postgres", "valkey", "minio", "control-plane"):
            assert "healthcheck" in compose["services"][service_name]
            assert compose["services"][service_name].get("volumes") or service_name == "control-plane"
    assert "postgres-backups" in primary["volumes"]
    assert "artifact-spool" in standby["volumes"]
    assert "postgres-backup" in primary["services"]


def test_artifacts_have_bidirectional_replication_health_and_failover_gates() -> None:
    reconcile = (
        INSTALLERS / "bin" / "reconcile-artifact-replication.sh"
    ).read_text(encoding="utf-8")
    health = (
        INSTALLERS / "bin" / "artifact-replication-health.sh"
    ).read_text(encoding="utf-8")
    validate = (
        INSTALLERS / "bin" / "validate-artifact-replication-receipt.sh"
    ).read_text(encoding="utf-8")
    assert "aos-primary-to-standby" in reconcile
    assert "aos-standby-to-primary" in reconcile
    assert "existing-objects,metadata-sync" in reconcile
    assert "mc version enable" in reconcile
    assert "primary-to-standby" in health
    assert "standby-to-primary" in health
    assert "FABRIC_ARTIFACT_REPLICATION_MAX_LAG_SECONDS" in health
    assert "artifact-replication-health.json" in health
    assert "RECEIPT_MAX_AGE_SECONDS" in validate
    for name in ("promote.sh", "failback.sh", "drill.sh"):
        script = (INSTALLERS / "bin" / name).read_text(encoding="utf-8")
        assert "artifact-replication" in script
    units = {path.name for path in (DEPLOY / "systemd").iterdir()}
    assert (
        "genomes-agentic-os-execution-fabric-artifact-replication.timer" in units
    )
    plist = (
        DEPLOY
        / "launchd"
        / "com.genomes.agentic-os.execution-fabric.artifact-replication.plist"
    )
    assert plist.is_file()


def test_primary_and_warm_standby_roles_are_separate() -> None:
    primary = _yaml(DEPLOY / "compose.genomesbox.yml")
    standby = _yaml(DEPLOY / "compose.bigmac.yml")
    assert primary["services"]["control-plane"]["profiles"] == ["primary"]
    assert primary["services"]["observer"]["profiles"] == ["primary"]
    assert primary["services"]["healer"]["profiles"] == ["primary"]
    assert primary["services"]["candidate-reporter"]["profiles"] == ["primary"]
    assert "standby" in standby["services"]["postgres"]["profiles"]
    assert standby["services"]["candidate-reporter"]["profiles"] == [
        "standby",
        "promoted",
    ]
    assert standby["services"]["control-plane"]["profiles"] == ["promoted"]
    assert standby["services"]["observer"]["profiles"] == ["promoted"]
    assert standby["services"]["healer"]["profiles"] == ["promoted"]
    assert primary["services"]["observer"]["command"] == [
        "node",
        "dist/src/observer-main.js",
    ]
    assert primary["services"]["healer"]["command"] == [
        "node",
        "dist/src/healer-main.js",
    ]
    for compose in (primary, standby):
        reporter = compose["services"]["candidate-reporter"]
        assert reporter["command"] == [
            "node",
            "/app/dist/candidate-reporter.mjs",
        ]
        assert reporter["environment"][
            "FABRIC_LEADERSHIP_CANDIDATE_TOKEN_FILE"
        ] == "/run/secrets/fabric-leadership-candidate-token"
        assert "fabric-leadership-candidate-token" in reporter["secrets"]
        assert "fabric-leadership-token" not in reporter["secrets"]
        assert "fabric-admin-token" not in reporter["secrets"]
        assert reporter["healthcheck"]["test"][-1] == "--healthcheck"
    assert standby["services"]["valkey"].get("ports") is None
    assert primary["services"]["valkey"].get("ports") is None


def test_observer_has_only_read_health_dependencies_and_scoped_artifact_credentials() -> None:
    forbidden_environment = {
        "FABRIC_VALKEY_URL",
        "FABRIC_API_TOKEN_FILE",
        "FABRIC_SUBMIT_TOKEN_FILE",
        "FABRIC_WORKER_BOOTSTRAP_CREDENTIALS_FILE",
        "FABRIC_ADMIN_TOKEN_FILE",
        "FABRIC_RELIABILITY_SOURCE_TOKENS_FILE",
        "FABRIC_EFFECT_CONSUMER_CREDENTIALS_FILE",
        "FABRIC_ALARM_DISPATCHER_CREDENTIALS_FILE",
        "FABRIC_LEADERSHIP_API_BASE",
        "FABRIC_LEADERSHIP_TOKEN_FILE",
        "FABRIC_LEADERSHIP_CANDIDATE_TOKEN_FILE",
        "FABRIC_LEADERSHIP_PUBLIC_KEY_FILE",
    }
    for name in ("compose.genomesbox.yml", "compose.bigmac.yml"):
        compose = _yaml(DEPLOY / name)
        observer = compose["services"]["observer"]
        assert forbidden_environment.isdisjoint(observer["environment"])
        assert set(observer["secrets"]) == {
            "artifact-observer-access-key",
            "artifact-observer-secret-key",
        }
        assert observer["networks"] == ["fabric-private"]
        assert observer["environment"]["FABRIC_ARTIFACT_ACCESS_KEY_FILE"] == (
            "/run/secrets/artifact-observer-access-key"
        )
        assert observer["environment"]["FABRIC_ARTIFACT_SECRET_KEY_FILE"] == (
            "/run/secrets/artifact-observer-secret-key"
        )
        assert "minio-root-user" not in observer["secrets"]
        assert "minio-root-password" not in observer["secrets"]
        assert {
            "minio-root-user",
            "minio-root-password",
            "artifact-observer-access-key",
            "artifact-observer-secret-key",
        } <= set(compose["services"]["minio-init"]["secrets"])
        init_command = compose["services"]["minio-init"]["entrypoint"][-1]
        assert "execution-fabric-observer-readonly" in init_command
        assert "s3:GetBucketLocation" in init_command
        assert "s3:ListBucket" in init_command
        assert "s3:GetObject" in init_command
        assert "s3:PutObject" not in init_command
        assert 'mc ls "observer/$${FABRIC_ARTIFACT_BUCKET}"' in init_command
        assert set(compose["services"]["minio"]["secrets"]) == {
            "minio-root-user",
            "minio-root-password",
        }


def test_scheduler_lifecycle_follows_promotion_and_durability_gates() -> None:
    promotion = (INSTALLERS / "bin" / "promote.sh").read_text(encoding="utf-8")
    durable = (
        INSTALLERS / "bin" / "enable-postgres-durable-primary.sh"
    ).read_text(encoding="utf-8")
    promoted_start = (
        "$compose --profile promoted up -d control-plane observer healer scheduler"
    )
    durable_start = '$compose --profile "$compose_profile" up -d --no-deps scheduler'
    scheduler_main = (
        SOURCE_ROOT
        / "services"
        / "execution-fabric-control-plane"
        / "src"
        / "scheduler-main.ts"
    ).read_text(encoding="utf-8")
    assert promoted_start in promotion
    assert promotion.index("--degraded-primary") < promotion.index(promoted_start)
    assert durable_start in durable
    assert durable.index("synchronous_commit = 'remote_apply'") < durable.index(
        durable_start
    )
    assert "await runtime.fabric.synchronizePolicy()" in scheduler_main


def test_promotion_is_api_fenced_before_any_local_mutation() -> None:
    script = (INSTALLERS / "bin" / "promote.sh").read_text(encoding="utf-8")
    assert "/api/v1/admin/leadership/status" in script
    assert "/api/v1/admin/leadership/promote" in script
    assert "promotionAllowed" in script
    assert "fabricEpoch" in script
    assert "fenceToken" in script
    assert "FABRIC_ENABLE_PROMOTION" in script
    assert script.index("/api/v1/admin/leadership/promote") < script.index(
        "pg_ctl promote"
    )
    assert "UPDATE fabric_state" not in script
    assert "psql" not in script


def test_hard_primary_loss_uses_configured_host_ids_and_bounded_degraded_gates() -> None:
    promotion = (INSTALLERS / "bin" / "promote.sh").read_text(encoding="utf-8")
    preflight = (INSTALLERS / "bin" / "preflight.sh").read_text(encoding="utf-8")
    failback = (INSTALLERS / "bin" / "failback.sh").read_text(encoding="utf-8")
    durable = (
        INSTALLERS / "bin" / "enable-postgres-durable-primary.sh"
    ).read_text(encoding="utf-8")
    for script in (promotion, preflight, failback, durable):
        assert "FABRIC_PRIMARY_HOST_ID" in script
        assert "FABRIC_STANDBY_HOST_ID" in script
    assert "--arg candidate \"$FABRIC_STANDBY_HOST_ID\"" in promotion
    assert "authorityMode:$authorityMode" in promotion
    assert "degradedDurationSeconds:$degradedDurationSeconds" in promotion
    assert "validate-backup-health-receipt.sh" in promotion
    assert "validate-artifact-replication-receipt.sh" in promotion
    assert "validate-emergency-bundle.sh" in promotion
    assert "degraded-primary.receipt.json" in promotion
    assert "execution-fabric-degraded-primary" in promotion
    assert "synchronous_commit = 'on'" in durable
    assert "current_setting('fsync')" in durable
    assert "current_setting('full_page_writes')" in durable
    assert "current_setting('archive_mode')" in durable
    assert ".candidates[$host].eligible" in failback
    assert "enable-postgres-durable-primary.sh --apply" in failback


def test_failback_is_manual_and_versioned() -> None:
    script = (INSTALLERS / "bin" / "failback.sh").read_text(encoding="utf-8")
    assert "--prepare" in script
    assert "--reseed" in script
    assert "--preparation-file" in script
    assert "--plan" in script
    assert "--approve" in script
    assert "--approval-file" in script
    assert 'mode:"manual_failback"' in script
    assert 'mode:"standby_reseed"' in script
    assert "/api/v1/admin/leadership/failback-prepare" in script
    assert "/api/v1/admin/leadership/failback-plan" in script
    assert "/api/v1/admin/leadership/failback-commit" in script
    assert script.index("failback-plan") < script.index("failback-commit")
    assert "{planToken:$planToken,approval:$approval[0]}" in script
    assert 'plan_path="$FABRIC_RUNTIME_STATE_DIR/failback.plan.json"' in script
    assert 'fabric_atomic_write "$plan_path"' in script
    assert script.index("failback-prepare") < script.index(
        "reseed-postgres-standby.sh --apply --target-role failback-target"
    )
    assert script.index("reseed-postgres-standby.sh --apply --target-role failback-target") < script.index(
        "failback-plan"
    )
    assert script.index("failback-plan") < script.index("failback-commit")
    assert script.index("failback-commit") < script.index(
        "activate-receipt.sh"
    )
    reseed = (
        INSTALLERS / "bin" / "reseed-postgres-standby.sh"
    ).read_text(encoding="utf-8")
    assert "--target-role failback-target|standby" in reseed
    assert "refusing to reseed the witnessed leader" in reseed
    assert "could not resolve exactly one PostgreSQL volume" in reseed
    assert "com.docker.compose.project=" in reseed
    assert "com.docker.compose.volume=" in reseed
    assert "--user postgres" in reseed
    assert "pg_basebackup" in reseed
    assert "pg_is_in_recovery()" in reseed
    assert "candidate-reporter-health.sh" in reseed
    assert "--require-standby" in reseed
    assert (INSTALLERS / "bin" / "failback.sh").stat().st_mode & 0o111
    assert (
        INSTALLERS / "bin" / "reseed-postgres-standby.sh"
    ).stat().st_mode & 0o111


def test_independent_witness_is_digest_pinned_and_durable() -> None:
    service = SOURCE_ROOT / "services" / "execution-fabric-leadership-witness"
    deployment = DEPLOY / "witness"
    assert (service / "Dockerfile").is_file()
    assert (service / "src" / "dynamo-store.ts").is_file()
    template = (deployment / "cloudformation.yml").read_text(encoding="utf-8")
    assert "AllowedPattern: \"^.+@sha256:[a-f0-9]{64}$\"" in template
    assert "PointInTimeRecoveryEnabled: true" in template
    assert "DeletionPolicy: Retain" in template
    assert "dynamodb:ConditionCheckItem" in template
    assert "WITNESS_ADMIN_TOKEN_FILE" in template
    assert "WITNESS_SIGNING_PRIVATE_KEY_FILE" in template
    assert "AdminTokenSecretArn" in template
    assert "SigningPrivateKeySecretArn" in template
    assert not any(part.isdigit() and len(part) == 12 for part in template.split(":"))
    docs = (DEPLOY / "README.md").read_text(encoding="utf-8")
    assert "does not yet expose" not in docs
    assert "operator prerequisites" in docs


def test_watchdog_alerts_locally_and_never_bypasses_promotion_contract() -> None:
    watchdog = (INSTALLERS / "bin" / "watchdog.sh").read_text(encoding="utf-8")
    library = (INSTALLERS / "bin" / "_lib.sh").read_text(encoding="utf-8")
    assert "FABRIC_FAILURE_THRESHOLD" in watchdog
    assert "FABRIC_AUTO_FAILOVER" in watchdog
    assert 'promote.sh" --apply' in watchdog
    assert "runtime.execution_fabric.health" in library
    assert "harness/bin/agentic-os-notify" in library
    deployment_docs = (DEPLOY / "README.md").read_text(encoding="utf-8")
    assert "bigmac watchdog" in deployment_docs
    assert "`runtime.execution_fabric.health`" in deployment_docs
    assert "`harness/registries/alerts.yml`" in deployment_docs
    assert "No deployment-specific alert registry exists" in deployment_docs


def test_policy_rotation_is_fenced_resumable_and_receipted() -> None:
    script = (INSTALLERS / "bin" / "rotate-policy.sh").read_text(
        encoding="utf-8"
    )
    assert "policy-rotation.pending.json" in script
    assert "/api/v1/admin/config/reload" in script
    assert "/api/v1/admin/leadership/config-digest-rotations/prepare" in script
    assert "/api/v1/admin/leadership/config-digest-rotations/commit" in script
    assert "/api/v1/admin/leadership/config-digest-rotations/abort" in script
    assert "pendingConfigDigestRotations" in script
    assert "preparationToken" in script
    assert "--resume" in script
    assert ".candidates[$primary].configDigest == $current" in script
    assert ".candidates[$standby].configDigest == $current" in script
    assert ".candidates[$primary].policyCandidateDigest == $candidate" in script
    assert ".candidates[$standby].policyCandidateDigest == $candidate" in script
    assert '.controlPlane.leadership.state=="active"' in script
    assert "policy-rotation-$rotation_id.receipt.json" in script
    assert "FABRIC_LEADERSHIP_ADMIN_TOKEN_FILE" in script
    promotion = (INSTALLERS / "bin" / "promote.sh").read_text(encoding="utf-8")
    assert '"$script_dir/rotate-policy.sh" --resume' in promotion


def test_policy_rotation_runs_prepare_reload_commit_and_readback(
    tmp_path: Path,
) -> None:
    old_digest = "a" * 64
    new_digest = "b" * 64
    rotation_id = "00000000-0000-4000-8000-000000000001"
    state = tmp_path / "state"
    fake_bin = tmp_path / "bin"
    tokens = tmp_path / "tokens"
    state.mkdir()
    fake_bin.mkdir()
    tokens.mkdir()
    for name in ("api", "admin", "witness-admin"):
        (tokens / name).write_text(f"{name}-token\n", encoding="utf-8")
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(
        f"""#!/bin/sh
set -eu
url=
while [ "$#" -gt 0 ]; do
  case "$1" in
    http://*) url=$1 ;;
    --data) shift ;;
  esac
  shift
done
case "$url" in
  http://witness/api/v1/admin/leadership/status)
    if [ -f "$FAKE_STATE_DIR/reloaded" ]; then
      replicated={new_digest}
    else
      replicated={old_digest}
    fi
    printf '%s\\n' '{{"currentLeader":"genomesbox","fabricEpoch":7,
      "configDigest":"{old_digest}","pendingConfigDigestRotations":[],
      "candidates":{{
        "genomesbox":{{"healthy":true,"configDigest":"'"$replicated"'",
          "policyCandidateDigest":"{new_digest}"}},
        "bigmac":{{"healthy":true,"configDigest":"'"$replicated"'",
          "policyCandidateDigest":"{new_digest}"}}}}}}'
    ;;
  http://witness/api/v1/admin/leadership/config-digest-rotations/prepare)
    printf '%s\\n' '{{"apiVersion":"execution-fabric-leadership/v1",
      "decision":"config_digest_rotation_prepared",
      "rotationId":"{rotation_id}","requestDigest":"{old_digest}",
      "expectedLeader":"genomesbox","expectedEpoch":7,
      "expectedCurrentDigest":"{old_digest}",
      "candidateDigest":"{new_digest}",
      "candidateHosts":["bigmac","genomesbox"],
      "preparationToken":"cpr1.payload.signature",
      "preparationTokenHash":"{old_digest}",
      "issuedAt":"2026-07-25T00:00:00Z",
      "expiresAt":"2026-07-25T00:05:00Z","expiresAtEpoch":1784937900}}'
    ;;
  http://control/api/v1/admin/config/reload)
    : >"$FAKE_STATE_DIR/reloaded"
    printf '%s\\n' '{{"appliedFingerprint":"{new_digest}",
      "receipt":{{"rotationId":"{rotation_id}",
      "appliedFingerprint":"{new_digest}"}}}}'
    ;;
  http://witness/api/v1/admin/leadership/config-digest-rotations/commit)
    : >"$FAKE_STATE_DIR/committed"
    printf '%s\\n' '{{"apiVersion":"execution-fabric-leadership/v1",
      "decision":"config_digest_rotated","rotationId":"{rotation_id}",
      "requestDigest":"{old_digest}","currentLeader":"genomesbox",
      "fabricEpoch":7,"previousConfigDigest":"{old_digest}",
      "configDigest":"{new_digest}","candidateHosts":["bigmac","genomesbox"],
      "preparationTokenHash":"{old_digest}",
      "committedAt":"2026-07-25T00:00:05Z"}}'
    ;;
  http://control/api/v1/status?limit=1)
    if [ -f "$FAKE_STATE_DIR/reloaded" ]; then
      applied={new_digest}
    else
      applied={old_digest}
    fi
    printf '%s\\n' '{{"config":{{"appliedFingerprint":"'"$applied"'"}},
      "controlPlane":{{"databasePolicyFingerprint":"'"$applied"'",
      "leadership":{{"state":"active"}}}}}}'
    ;;
  *) exit 22 ;;
esac
""",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)
    fake_logger = fake_bin / "logger"
    fake_logger.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_logger.chmod(0o755)
    runtime = tmp_path / "runtime.env"
    runtime.write_text(
        "\n".join(
            (
                f"FABRIC_OS_ROOT={tmp_path / 'os'}",
                f"FABRIC_RUNTIME_STATE_DIR={state}",
                "FABRIC_API_BASE=http://control",
                f"FABRIC_API_TOKEN_FILE={tokens / 'api'}",
                f"FABRIC_ADMIN_TOKEN_FILE={tokens / 'admin'}",
                "FABRIC_LEADERSHIP_API_BASE=http://witness",
                f"FABRIC_LEADERSHIP_ADMIN_TOKEN_FILE={tokens / 'witness-admin'}",
                "FABRIC_HOST_ID=genomesbox",
                "FABRIC_PRIMARY_HOST_ID=genomesbox",
                "FABRIC_STANDBY_HOST_ID=bigmac",
                f"FAKE_STATE_DIR={state}",
                "",
            )
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            str(INSTALLERS / "bin" / "rotate-policy.sh"),
            old_digest,
            new_digest,
            rotation_id,
        ],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "FABRIC_RUNTIME_ENV_FILE": str(runtime),
        },
    )
    assert result.returncode == 0, result.stderr
    receipt = Path(result.stdout.strip())
    assert receipt.is_file()
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["rotationId"] == rotation_id
    assert payload["witness"]["decision"] == "config_digest_rotated"
    assert (state / "committed").is_file()
    assert not (state / "policy-rotation.pending.json").exists()


def test_policy_rotation_resume_aborts_expired_pre_database_preparation(
    tmp_path: Path,
) -> None:
    old_digest = "a" * 64
    new_digest = "b" * 64
    rotation_id = "00000000-0000-4000-8000-000000000002"
    state = tmp_path / "state"
    fake_bin = tmp_path / "bin"
    tokens = tmp_path / "tokens"
    state.mkdir()
    fake_bin.mkdir()
    tokens.mkdir()
    for name in ("api", "admin", "witness-admin"):
        (tokens / name).write_text(f"{name}-token\n", encoding="utf-8")
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(
        f"""#!/bin/sh
set -eu
url=
while [ "$#" -gt 0 ]; do
  case "$1" in
    http://*) url=$1 ;;
    --data) shift ;;
  esac
  shift
done
case "$url" in
  http://witness/api/v1/admin/leadership/status)
    printf '%s\\n' '{{"currentLeader":"genomesbox","fabricEpoch":7,
      "configDigest":"{old_digest}",
      "pendingConfigDigestRotations":[{{
        "rotationId":"{rotation_id}","expectedLeader":"genomesbox",
        "expectedEpoch":7,"expectedCurrentDigest":"{old_digest}",
        "candidateDigest":"{new_digest}",
        "preparationToken":"cpr1.payload.signature","expired":true}}],
      "candidates":{{
        "genomesbox":{{"healthy":false,"configDigest":"{old_digest}"}},
        "bigmac":{{"healthy":true,"configDigest":"{old_digest}"}}}}}}'
    ;;
  http://witness/api/v1/admin/leadership/config-digest-rotations/abort)
    : >"$FAKE_STATE_DIR/aborted"
    printf '%s\\n' '{{"apiVersion":"execution-fabric-leadership/v1",
      "decision":"config_digest_rotation_aborted",
      "rotationId":"{rotation_id}","requestDigest":"{old_digest}",
      "currentLeader":"genomesbox","fabricEpoch":7,
      "configDigest":"{old_digest}","candidateDigest":"{new_digest}",
      "evidenceHost":"bigmac","preparationTokenHash":"{old_digest}",
      "expiredAt":"2026-07-25T00:05:00Z",
      "abortedAt":"2026-07-25T00:06:00Z"}}'
    ;;
  *) exit 22 ;;
esac
""",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)
    fake_logger = fake_bin / "logger"
    fake_logger.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_logger.chmod(0o755)
    runtime = tmp_path / "runtime.env"
    runtime.write_text(
        "\n".join(
            (
                f"FABRIC_OS_ROOT={tmp_path / 'os'}",
                f"FABRIC_RUNTIME_STATE_DIR={state}",
                "FABRIC_API_BASE=http://control",
                f"FABRIC_API_TOKEN_FILE={tokens / 'api'}",
                f"FABRIC_ADMIN_TOKEN_FILE={tokens / 'admin'}",
                "FABRIC_LEADERSHIP_API_BASE=http://witness",
                f"FABRIC_LEADERSHIP_ADMIN_TOKEN_FILE={tokens / 'witness-admin'}",
                "FABRIC_HOST_ID=bigmac",
                "FABRIC_PRIMARY_HOST_ID=genomesbox",
                "FABRIC_STANDBY_HOST_ID=bigmac",
                f"FAKE_STATE_DIR={state}",
                "",
            )
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [str(INSTALLERS / "bin" / "rotate-policy.sh"), "--resume"],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "FABRIC_RUNTIME_ENV_FILE": str(runtime),
        },
    )
    assert result.returncode == 0, result.stderr
    assert "aborted expired pre-database policy rotation" in result.stdout
    assert (state / "aborted").is_file()


def test_candidate_reporting_is_measured_fresh_and_independently_alerted() -> None:
    reporter = (
        DEPLOY / "scripts" / "candidate-reporter.mjs"
    ).read_text(encoding="utf-8")
    health = (
        INSTALLERS / "bin" / "candidate-reporter-health.sh"
    ).read_text(encoding="utf-8")
    assert "pg_is_in_recovery()" in reporter
    assert "pg_last_wal_receive_lsn()" in reporter
    assert "pg_last_wal_replay_lsn()" in reporter
    assert "clock_timestamp()" in reporter
    assert "FABRIC_LEADERSHIP_CANDIDATE_TOKEN_FILE" in reporter
    assert "FABRIC_LEADERSHIP_ADMIN_TOKEN_FILE" not in reporter
    assert 'mode: replication.inRecovery ? "standby" : "active"' in reporter
    assert "FABRIC_CANDIDATE_REPORT_INTERVAL_SECONDS" in reporter
    assert "FABRIC_CANDIDATE_HEARTBEAT_MAX_AGE_SECONDS" in health
    assert "candidate-reporter container is not uniquely running" in health
    assert "fabric_notify critical" in health
    assert "--require-standby" in health
    assert "--require-active" in health

    units = {path.name for path in (DEPLOY / "systemd").iterdir()}
    assert (
        "genomes-agentic-os-execution-fabric-candidate-reporter-health.service"
        in units
    )
    assert (
        "genomes-agentic-os-execution-fabric-candidate-reporter-health.timer"
        in units
    )
    assert (
        DEPLOY
        / "launchd"
        / "com.genomes.agentic-os.execution-fabric.candidate-reporter-health.plist"
    ).is_file()

    promotion = (INSTALLERS / "bin" / "promote.sh").read_text(encoding="utf-8")
    activation = (
        INSTALLERS / "bin" / "activate-receipt.sh"
    ).read_text(encoding="utf-8")
    drill = (INSTALLERS / "bin" / "drill.sh").read_text(encoding="utf-8")
    preflight = (INSTALLERS / "bin" / "preflight.sh").read_text(encoding="utf-8")
    assert promotion.index("--require-standby") < promotion.index(
        "/api/v1/admin/leadership/promote"
    )
    assert "--require-active" in promotion
    assert "candidateHealthReceiptSha256" in promotion
    assert "--require-active" in activation
    assert "candidate_health_receipt_sha256" in drill
    assert "candidate-reporter service is missing" in preflight


def test_deployment_reuses_canonical_instance_configuration() -> None:
    manifest = _yaml(DEPLOY / "emergency-bundle" / "manifest.yml")
    canonical = set(manifest["canonical_configs"])
    assert "harness/config/execution-fabric.yml" in canonical
    assert "harness/registries/hosts-routing.yml" in canonical
    assert "harness/registries/alerts.yml" in canonical
    assert {"config/hosts.yml", "harness/config/hosts.yml"} <= canonical
    assert not list(DEPLOY.rglob("queue*.yml"))
    assert not list(DEPLOY.rglob("alerts.yml"))
    assert not list(DEPLOY.rglob("hosts.yml"))


def test_systemd_units_cover_primary_observer_watchdog_and_backups() -> None:
    unit_dir = DEPLOY / "systemd"
    units = {path.name for path in unit_dir.iterdir()}
    assert "genomes-agentic-os-execution-fabric-primary.service" in units
    assert "genomes-agentic-os-execution-fabric-api.service" in units
    assert "genomes-agentic-os-execution-fabric-health-observer.service" in units
    assert "genomes-agentic-os-execution-fabric-healer.service" in units
    assert "genomes-agentic-os-execution-fabric-observer.timer" in units
    assert "genomes-agentic-os-execution-fabric-watchdog.timer" in units
    assert "genomes-agentic-os-execution-fabric-backup.timer" in units
    primary = (
        unit_dir / "genomes-agentic-os-execution-fabric-primary.service"
    ).read_text(encoding="utf-8")
    assert "EnvironmentFile=/etc/genomes-agentic-os/execution-fabric/runtime.env" in primary
    assert "--profile primary" in primary


def test_launchd_definitions_are_valid_and_cover_required_bigmac_roles() -> None:
    launchd = DEPLOY / "launchd"
    labels: set[str] = set()
    for path in launchd.glob("*.plist"):
        with path.open("rb") as handle:
            document = plistlib.load(handle)
        labels.add(document["Label"])
        assert document["ProgramArguments"][0].startswith("__INSTALL_ROOT__/bin/")
        assert document["EnvironmentVariables"]["FABRIC_RUNTIME_ENV_FILE"] == "__RUNTIME_ENV__"
    for role in ("standby", "worker", "observer", "watchdog"):
        assert f"com.genomes.agentic-os.execution-fabric.{role}" in labels
    for role in ("api-role", "health-observer-role", "healer-role"):
        assert f"com.genomes.agentic-os.execution-fabric.{role}" in labels
    assert "com.genomes.agentic-os.execution-fabric.alarm-dispatcher" in labels


def test_alarm_dispatch_is_separate_filtered_and_receipt_backed() -> None:
    dispatcher = (
        INSTALLERS / "bin" / "dispatch-alarms.sh"
    ).read_text(encoding="utf-8")
    assert "/api/v1/alarms/claim" in dispatcher
    assert "/api/v1/alarms/${alarm_id}/deliver" in dispatcher
    assert "/api/v1/alarms/${alarm_id}/fail" in dispatcher
    assert "--source runtime.execution_fabric.health" in dispatcher
    assert "FABRIC_ALARM_DISPATCHER_TOKEN_FILE" in dispatcher
    assert 'fabric_api_post_bearer_value' in dispatcher
    assert '"$claim_token"' in dispatcher
    assert "FABRIC_ADMIN_TOKEN_FILE" not in dispatcher


def test_helm_worker_is_digest_pinned_api_only_and_network_restricted() -> None:
    chart = DEPLOY / "helm" / "los-agents"
    deployment = (chart / "templates" / "deployment.yaml").read_text(encoding="utf-8")
    values = _yaml(chart / "values.yaml")
    values_schema = json.loads(
        (chart / "values.schema.json").read_text(encoding="utf-8")
    )
    network = (chart / "templates" / "networkpolicy.yaml").read_text(encoding="utf-8")
    configmap = (chart / "templates" / "configmap.yaml").read_text(encoding="utf-8")
    assert "image.digest must be an immutable sha256 digest" in deployment
    assert '@{{ .Values.image.digest }}' in deployment
    assert "automountServiceAccountToken: false" in deployment
    assert "kind: NetworkPolicy" in network
    assert "ingress: []" in network
    assert "FABRIC_API_BASE" in configmap
    assert "FABRIC_API_VERSION" in configmap
    assert values["secrets"]["existingSecret"] == ""
    assert values["replicaCount"] == 1
    assert values["secrets"]["keys"]["workerBootstrapToken"] == (
        "worker-bootstrap-token"
    )
    assert values["worker"]["id"] == ""
    assert values["worker"]["bootstrapId"] == ""
    assert values["worker"]["hostId"] == ""
    assert values["worker"]["acceptedQueues"] == ["codex"]
    assert values["worker"]["capabilities"] == ["codex.task"]
    assert values["storage"]["existingClaim"] == ""
    assert "secrets.existingSecret must name an operator-owned Kubernetes Secret" in deployment
    assert "storage.existingClaim must name an RWX claim" in deployment
    assert "worker.hostId must be a canonical registered host alias" in deployment
    assert "worker.id must be a durable scoped worker identity" in deployment
    assert "worker.bootstrapId must match the scoped bootstrap credential" in deployment
    assert "name: FABRIC_HOST_ID" in deployment
    assert "name: FABRIC_WORKER_HOST_ID" in deployment
    assert "name: FABRIC_WORKER_ID" in deployment
    assert "name: FABRIC_WORKER_BOOTSTRAP_ID" in deployment
    assert "AGENTIC_OS_EXECUTION_FABRIC_WORKER_TOKEN_FILE" in deployment
    assert "secretName: {{ .Values.secrets.existingSecret | quote }}" in deployment
    assert "workerBootstrapToken" in (
        values_schema["properties"]["secrets"]["properties"]["keys"]["properties"]
    )


def test_shell_assets_are_syntax_valid() -> None:
    scripts = sorted((INSTALLERS / "bin").glob("*.sh"))
    scripts.extend(sorted(DEPLOY.glob("scripts/*.sh")))
    scripts.extend(
        [
            INSTALLERS / "install-linux.sh",
            INSTALLERS / "install-macos.sh",
            INSTALLERS / "activate-linux.sh",
            INSTALLERS / "activate-macos.sh",
        ]
    )
    assert scripts
    for script in scripts:
        subprocess.run(["sh", "-n", str(script)], check=True)


def test_linux_activation_is_explicit_preflight_gated_and_repeatable(
    tmp_path: Path,
) -> None:
    installer = tmp_path / "installer"
    installer.mkdir()
    shutil.copy2(INSTALLERS / "activate-linux.sh", installer / "activate-linux.sh")
    activation_log = tmp_path / "activation.log"
    _write_executable(
        installer / "bin/preflight.sh",
        """#!/bin/sh
printf 'preflight %s\n' "$1" >>"$ACTIVATION_LOG"
[ "${PREFLIGHT_FAIL:-false}" != true ]
""",
    )
    fake_bin = tmp_path / "bin"
    _write_executable(
        fake_bin / "id",
        """#!/bin/sh
[ "${1:-}" = -u ] && printf '0\n'
""",
    )
    _write_executable(
        fake_bin / "systemctl",
        """#!/bin/sh
printf 'systemctl %s\n' "$*" >>"$ACTIVATION_LOG"
""",
    )
    env = {
        **os.environ,
        "ACTIVATION_LOG": str(activation_log),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
    }

    blocked = subprocess.run(
        ["sh", str(installer / "activate-linux.sh"), "--apply"],
        check=False,
        capture_output=True,
        text=True,
        env={**env, "PREFLIGHT_FAIL": "true"},
    )
    assert blocked.returncode != 0
    assert activation_log.read_text(encoding="utf-8").splitlines() == [
        "preflight primary"
    ]

    activation_log.write_text("", encoding="utf-8")
    for _ in range(2):
        subprocess.run(
            ["sh", str(installer / "activate-linux.sh"), "--apply"],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
    lines = activation_log.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "preflight primary"
    assert lines.index("systemctl daemon-reload") > lines.index("preflight primary")
    assert not any("--now" in line or "restart" in line for line in lines)
    assert lines.count(
        "systemctl start genomes-agentic-os-execution-fabric-primary.service"
    ) == 2


def test_macos_activation_preflights_before_bootstrap_and_skips_loaded_jobs(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    installer = tmp_path / "installer"
    installer.mkdir()
    shutil.copy2(INSTALLERS / "activate-macos.sh", installer / "activate-macos.sh")
    activation_log = tmp_path / "activation.log"
    launch_state = tmp_path / "launch-state"
    launch_state.mkdir()
    _write_executable(
        installer / "bin/preflight.sh",
        """#!/bin/sh
printf 'preflight %s\n' "$1" >>"$ACTIVATION_LOG"
[ "${PREFLIGHT_FAIL:-false}" != true ]
""",
    )
    fake_bin = tmp_path / "bin"
    _write_executable(fake_bin / "uname", "#!/bin/sh\nprintf 'Darwin\\n'\n")
    _write_executable(
        fake_bin / "id",
        """#!/bin/sh
[ "${1:-}" = -u ] && printf '501\n'
""",
    )
    _write_executable(
        fake_bin / "launchctl",
        """#!/bin/sh
case "$1" in
  print)
    label=${2##*/}
    [ -f "$LAUNCH_STATE/$label" ]
    ;;
  bootstrap)
    label=$(basename "$3" .plist)
    printf 'bootstrap %s\n' "$label" >>"$ACTIVATION_LOG"
    : >"$LAUNCH_STATE/$label"
    ;;
  *) exit 64 ;;
esac
""",
    )
    launch_agents = home / "Library/LaunchAgents"
    launch_agents.mkdir(parents=True)
    suffixes = (
        "standby",
        "worker",
        "observer",
        "watchdog",
        "alarm-dispatcher",
        "artifact-replication",
        "candidate-reporter-health",
        "scheduler-role",
    )
    for suffix in suffixes:
        (
            launch_agents
            / f"com.genomes.agentic-os.execution-fabric.{suffix}.plist"
        ).write_text("<plist/>", encoding="utf-8")
    env = {
        **os.environ,
        "ACTIVATION_LOG": str(activation_log),
        "HOME": str(home),
        "LAUNCH_STATE": str(launch_state),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
    }

    blocked = subprocess.run(
        ["sh", str(installer / "activate-macos.sh"), "--apply"],
        check=False,
        capture_output=True,
        text=True,
        env={**env, "PREFLIGHT_FAIL": "true"},
    )
    assert blocked.returncode != 0
    assert activation_log.read_text(encoding="utf-8").splitlines() == [
        "preflight standby"
    ]

    activation_log.write_text("", encoding="utf-8")
    for _ in range(2):
        subprocess.run(
            ["sh", str(installer / "activate-macos.sh"), "--apply"],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
    lines = activation_log.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "preflight standby"
    assert lines.count("preflight standby") == 2
    assert len([line for line in lines if line.startswith("bootstrap ")]) == len(
        suffixes
    )


def test_installers_can_activate_an_existing_current_release_without_recopy() -> None:
    for platform in ("linux", "macos"):
        script = (INSTALLERS / f"install-{platform}.sh").read_text(encoding="utf-8")
        assert "already_installed=true" in script
        assert "release is installed but is not current" in script
        assert f"activate-{platform}.sh" in script
        assert '"$activator" --apply' in script
        assert "cp -R" in script.split("else", maxsplit=1)[1]


def test_macos_installer_rerun_activates_existing_release_without_reinstall(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    fake_bin = tmp_path / "bin"
    activation_log = tmp_path / "activation.log"
    _write_executable(fake_bin / "uname", "#!/bin/sh\nprintf 'Darwin\\n'\n")
    _write_executable(fake_bin / "plutil", "#!/bin/sh\nexit 0\n")
    _write_executable(
        fake_bin / "launchctl",
        """#!/bin/sh
case "$1" in
  print) exit 1 ;;
  bootstrap) printf 'bootstrap %s\n' "$3" >>"$ACTIVATION_LOG" ;;
  *) exit 64 ;;
esac
""",
    )
    env = {
        **os.environ,
        "ACTIVATION_LOG": str(activation_log),
        "HOME": str(home),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
    }
    command = [
        "sh",
        str(INSTALLERS / "install-macos.sh"),
        "--apply",
        "--source-root",
        str(SOURCE_ROOT),
        "--release",
        "test-release",
    ]
    subprocess.run(command, check=True, capture_output=True, text=True, env=env)

    release = (
        home
        / "Library/Application Support/GenomesAgenticOS/execution-fabric"
        / "releases/test-release"
    )
    _write_executable(
        release / "installers/bin/preflight.sh",
        """#!/bin/sh
printf 'preflight %s\n' "$1" >>"$ACTIVATION_LOG"
""",
    )
    activated = subprocess.run(
        [*command, "--enable"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert activated.returncode == 0, activated.stderr
    lines = activation_log.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "preflight standby"
    assert len([line for line in lines if line.startswith("bootstrap ")]) == 8
    assert "preflight %s" in (
        release / "installers/bin/preflight.sh"
    ).read_text(encoding="utf-8")


def test_packaged_python_worker_is_the_default_governed_host_entrypoint() -> None:
    launcher = INSTALLERS / "bin/python-worker.sh"
    result = subprocess.run(
        ["sh", str(launcher), "--preflight"],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "FABRIC_WORKER_PYTHON": sys.executable,
            "PYTHONPATH": str(SOURCE_ROOT / "src"),
        },
    )
    assert result.returncode == 0, result.stderr
    worker = (INSTALLERS / "bin/worker.sh").read_text(encoding="utf-8")
    preflight = (INSTALLERS / "bin/preflight.sh").read_text(encoding="utf-8")
    assert '${FABRIC_WORKER_EXECUTABLE:-"$script_dir/python-worker.sh"}' in worker
    assert '"$worker_executable" --preflight' in preflight


def test_workers_use_stable_signed_leader_gateway_and_receipts_are_verified() -> None:
    worker = (INSTALLERS / "bin" / "worker.sh").read_text(encoding="utf-8")
    promotion = (INSTALLERS / "bin" / "promote.sh").read_text(encoding="utf-8")
    failback = (INSTALLERS / "bin" / "failback.sh").read_text(encoding="utf-8")
    verifier = INSTALLERS / "bin" / "verify-leadership-receipt.mjs"
    assert "FABRIC_GATEWAY_API_BASE" in worker
    assert "FABRIC_PRIMARY_API_BASE" not in worker
    assert verifier.is_file()
    assert "verify-leadership-receipt.mjs" in promotion
    assert promotion.index("verify-leadership-receipt.mjs") < promotion.index(
        "pg_ctl promote"
    )
    assert "verify-leadership-receipt.mjs" in failback
    for name in ("compose.genomesbox.yml", "compose.bigmac.yml"):
        compose = _yaml(DEPLOY / name)
        gateway = compose["services"]["gateway"]
        assert gateway["command"] == ["node", "dist/src/gateway-main.js"]
        assert "FABRIC_GATEWAY_LEADER_ENDPOINTS" in gateway["environment"]
        assert "fabric-leadership-public-key" in gateway["secrets"]


def test_bundle_builder_and_validator_round_trip(tmp_path: Path) -> None:
    os_root = tmp_path / "os"
    for relative in (
        "harness/config/execution-fabric.yml",
        "harness/config/hosts.yml",
        "harness/registries/hosts-routing.yml",
        "harness/registries/alerts.yml",
    ):
        target = os_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("schema_version: 1\n", encoding="utf-8")

    digest = "1" * 64
    image_lock = tmp_path / "images.lock.env"
    image_lock.write_text(
        "\n".join(
            f"{name}=example.invalid/{name.lower()}@sha256:{digest}"
            for name in (
                "FABRIC_CONTROL_PLANE_IMAGE",
                "FABRIC_POSTGRES_IMAGE",
                "FABRIC_VALKEY_IMAGE",
                "FABRIC_MINIO_IMAGE",
                "FABRIC_MINIO_CLIENT_IMAGE",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "bundle"
    subprocess.run(
        [
            "sh",
            str(INSTALLERS / "bin" / "build-emergency-bundle.sh"),
            "--source-root",
            str(SOURCE_ROOT),
            "--os-root",
            str(os_root),
            "--image-lock",
            str(image_lock),
            "--output",
            str(output),
            "--release",
            "test-release",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["sh", str(INSTALLERS / "bin" / "validate-emergency-bundle.sh"), str(output)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert (output / "CHECKSUMS.sha256").is_file()
    assert "secrets_included=false" in (output / "RELEASE").read_text(encoding="utf-8")


def test_documentation_exposes_the_implemented_witness_and_activation_boundary() -> None:
    readme = (DEPLOY / "README.md").read_text(encoding="utf-8")
    normalized = " ".join(readme.split())
    assert "/api/v1/admin/leadership/*" in readme
    assert "DynamoDB conditional transactions" in normalized
    assert "Source availability does not activate the witness" in normalized
    assert "operator prerequisites" in normalized
    assert re.search(r"Failback is always manual", readme)
