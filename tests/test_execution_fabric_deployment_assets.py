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
        "oci_witness",
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
        for service_name, service in compose["services"].items():
            image = service["image"]
            assert image.startswith("${FABRIC_")
            if service_name == "leadership-witness":
                assert service["profiles"] == ["standalone-primary"]
                assert "FABRIC_WITNESS_IMAGE" in image
            else:
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


def test_datastore_credentials_are_file_mounted_and_urls_are_process_local(
    tmp_path: Path,
) -> None:
    runtime_env = (DEPLOY / "runtime.env.example").read_text(encoding="utf-8")
    assert "FABRIC_DATABASE_URL=" not in runtime_env
    assert "FABRIC_VALKEY_URL=" not in runtime_env

    for name in ("compose.genomesbox.yml", "compose.bigmac.yml"):
        compose = _yaml(DEPLOY / name)
        assert "valkey-acl" not in compose["secrets"]
        assert {"postgres-password", "valkey-app-password"} <= set(
            compose["secrets"]
        )
        for service_name in ("candidate-reporter", "control-plane", "observer", "healer"):
            service = compose["services"][service_name]
            assert "FABRIC_DATABASE_URL" not in service["environment"]
            assert service["environment"]["FABRIC_DATABASE_PASSWORD_FILE"] == (
                "/run/secrets/postgres-password"
            )
            assert "postgres-password" in service["secrets"]
            assert service["entrypoint"] == ["/usr/local/bin/fabric-datastore-env"]
        for service_name in ("control-plane", "healer"):
            service = compose["services"][service_name]
            assert "FABRIC_VALKEY_URL" not in service["environment"]
            assert service["environment"]["FABRIC_VALKEY_PASSWORD_FILE"] == (
                "/run/secrets/valkey-app-password"
            )
            assert "valkey-app-password" in service["secrets"]

    postgres_password = "p" * 40
    valkey_password = "v" * 40
    postgres_file = tmp_path / "postgres-password"
    valkey_file = tmp_path / "valkey-app-password"
    postgres_file.write_text(postgres_password, encoding="utf-8")
    valkey_file.write_text(valkey_password, encoding="utf-8")
    result = subprocess.run(
        [
            "sh",
            str(DEPLOY / "scripts/datastore-env-entrypoint.sh"),
            "sh",
            "-c",
            'printf "%s\\n%s\\n" "$FABRIC_DATABASE_URL" "$FABRIC_VALKEY_URL"',
        ],
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "FABRIC_DATABASE_PASSWORD_FILE": str(postgres_file),
            "FABRIC_VALKEY_PASSWORD_FILE": str(valkey_file),
        },
    )
    assert result.stdout.splitlines() == [
        f"postgresql://fabric:{postgres_password}@postgres:5432/execution_fabric",
        f"redis://fabric:{valkey_password}@valkey:6379/0",
    ]


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
        assert compose["services"]["control-plane"]["command"] == [
            "node",
            "dist/src/main.js",
        ]
        observer = compose["services"]["observer"]
        assert observer["healthcheck"]["test"][-1].endswith(
            "role-healthcheck.js observer"
        )
        assert compose["services"]["healer"]["healthcheck"]["test"] == [
            "CMD-SHELL",
            "/usr/local/bin/fabric-datastore-env node dist/src/role-healthcheck.js healer",
        ]
        assert compose["services"]["scheduler"]["healthcheck"]["test"][-1].endswith(
            "role-healthcheck.js scheduler"
        )
        for role in ("candidate-reporter", "control-plane", "observer", "healer"):
            volumes = compose["services"][role]["volumes"]
            assert any(
                volume.endswith(
                    "/harness/config:/etc/agentic-os/policy-bundle/config:ro"
                )
                for volume in volumes
            )
            if role != "candidate-reporter":
                assert any(
                    volume.endswith(
                        "/harness/schemas:/etc/agentic-os/policy-bundle/schemas:ro"
                    )
                    for volume in volumes
                )
            assert not any("execution-fabric.yml:" in volume for volume in volumes)
        for role in ("observer", "healer", "scheduler"):
            assert compose["services"][role]["healthcheck"]["start_period"] == (
                "${FABRIC_ROLE_HEALTH_STARTUP_GRACE_SECONDS:-90}s"
            )
        assert compose["services"]["gateway"]["healthcheck"]["test"][-1].endswith(
            "127.0.0.1:3181/healthz || exit 1"
        )
        assert forbidden_environment.isdisjoint(observer["environment"])
        assert set(observer["secrets"]) == {
            "postgres-password",
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
        assert "__BUCKET__" not in init_command
        assert "| sed " not in init_command
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
    promoted_start = "--profile promoted up -d control-plane observer healer scheduler"
    durable_start = '--profile "$compose_profile" up -d --no-deps scheduler'
    scheduler_main = (
        SOURCE_ROOT
        / "services"
        / "execution-fabric-control-plane"
        / "src"
        / "scheduler-main.ts"
    ).read_text(encoding="utf-8")
    assert 'fabric_compose "$compose_file"' in promotion
    assert promoted_start in promotion
    assert promotion.index("--degraded-primary") < promotion.index(promoted_start)
    assert 'fabric_compose "$compose_file"' in durable
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
    assert "SELECT pg_is_in_recovery()" in script
    assert script.index("fenceToken") < script.index("SELECT pg_is_in_recovery()")


def test_promotion_has_durable_lookup_and_postgres_resume_journal() -> None:
    script = (INSTALLERS / "bin" / "promote.sh").read_text(encoding="utf-8")
    assert "execution-fabric-promotion-operation/v1" in script
    assert "/api/v1/admin/leadership/promotions/$promotion_id" in script
    assert "promotion_journal_phase witness_committed" in script
    assert "promotion_journal_phase postgres_promoted" in script
    assert "promotion_journal_phase complete" in script
    assert "PostgreSQL is already promoted; resuming" in script
    assert script.index("promotion.operation.json") < script.index(
        "/api/v1/admin/leadership/promote"
    )
    assert script.index("witness_committed") < script.index("pg_ctl promote")


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
    dockerfile = (service / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM --platform=$BUILDPLATFORM" in dockerfile
    assert "npm prune --omit=dev --ignore-scripts" in dockerfile
    assert "COPY --from=build /app/node_modules ./node_modules" in dockerfile
    runtime_stage = dockerfile.split(" AS runtime", maxsplit=1)[1]
    assert "RUN npm ci" not in runtime_stage
    assert (service / "src" / "sqlite-store.ts").is_file()
    assert not (service / "src" / "dynamo-store.ts").exists()
    assert not (deployment / "cloudformation.yml").exists()
    manifest = _yaml(deployment / "manifest.yml")
    assert manifest["container"]["immutable_digest_required"] is True
    assert manifest["container"]["network_mode"] == "host"
    assert manifest["container"]["bind_variable"] == "WITNESS_TAILSCALE_IP"
    assert manifest["safety"]["candidate_host_may_run_witness"] is False
    assert manifest["safety"]["two_candidate_hosts_are_not_quorum"] is True
    assert manifest["safety"]["no_witness_behavior"] == "manual_fail_closed"
    assert manifest["safety"]["singleton_storage_lease"] is True
    assert manifest["safety"]["explicit_one_time_bootstrap"] is True
    preflight = (deployment / "bin/preflight.sh").read_text(encoding="utf-8")
    runner = (deployment / "bin/run.sh").read_text(encoding="utf-8")
    assert "tailscale ip -4" in preflight
    assert 'grep -Fx "$WITNESS_TAILSCALE_IP"' in preflight
    assert "candidate tokens must name at least two unique candidates" in preflight
    assert "--network host" in runner
    assert "--read-only" in runner
    assert "--cap-drop ALL" in runner
    assert "--security-opt no-new-privileges" in runner
    assert '--user "${WITNESS_UID:-3195}:${WITNESS_GID:-3195}"' in runner
    assert "container-secrets" in runner
    assert (deployment / "bin/preflight.sh").stat().st_mode & 0o111
    assert (deployment / "bin/run.sh").stat().st_mode & 0o111
    oci_smoke = SOURCE_ROOT / "tests/scripts/run-witness-oci-smoke.sh"
    assert oci_smoke.is_file()
    assert oci_smoke.stat().st_mode & 0o111
    service_package = (service / "package.json").read_text(encoding="utf-8")
    service_lock = (service / "pnpm-lock.yaml").read_text(encoding="utf-8")
    assert "@aws-sdk" not in service_package
    assert "@aws-sdk" not in service_lock
    docs = (DEPLOY / "README.md").read_text(encoding="utf-8")
    assert "does not yet expose" not in docs
    assert "operator prerequisites" in docs


def test_witness_runbook_documents_supervised_portable_health_alerts() -> None:
    runbook = (DEPLOY / "witness/RUNBOOK.md").read_text(encoding="utf-8")
    assert "manual_fail_closed" in runbook
    assert "runtime.execution_fabric.health" in runbook
    assert "health.json" in runbook
    assert "SQLite" in runbook
    assert "systemd timer" in runbook
    assert "automaticPromotionEligible" in runbook
    monitor = (DEPLOY / "witness/bin/monitor.sh").read_text(encoding="utf-8")
    assert "execution-fabric-witness-health/v2" in monitor
    assert "witness_notify critical" in monitor
    assert "automaticPromotionEligible" in monitor
    systemd = DEPLOY / "witness/systemd"
    assert (systemd / "genomes-agentic-os-execution-fabric-witness-monitor.service").is_file()
    assert (systemd / "genomes-agentic-os-execution-fabric-witness-monitor.timer").is_file()


def test_witness_manual_mode_is_explicit_inert_and_fail_closed(
    tmp_path: Path,
) -> None:
    environment = tmp_path / "witness.env"
    environment.write_text(
        "\n".join(
            (
                "WITNESS_MODE=manual_fail_closed",
                "FABRIC_AUTO_FAILOVER=false",
                "FABRIC_ENABLE_PROMOTION=false",
                "",
            )
        ),
        encoding="utf-8",
    )
    preflight = subprocess.run(
        [str(DEPLOY / "witness/bin/preflight.sh")],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "WITNESS_ENV_FILE": str(environment)},
    )
    assert preflight.returncode == 0, preflight.stderr
    assert "no witness container will start" in preflight.stdout

    unsafe = environment.read_text(encoding="utf-8").replace(
        "FABRIC_ENABLE_PROMOTION=false",
        "FABRIC_ENABLE_PROMOTION=true",
    )
    environment.write_text(unsafe, encoding="utf-8")
    blocked = subprocess.run(
        [str(DEPLOY / "witness/bin/preflight.sh")],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "WITNESS_ENV_FILE": str(environment)},
    )
    assert blocked.returncode == 78
    assert "requires automatic failover and promotion disabled" in blocked.stderr


def test_witness_installer_is_inert_and_manual_activation_starts_nothing(
    tmp_path: Path,
) -> None:
    install_root = tmp_path / "installed-witness"
    environment = tmp_path / "config" / "witness.env"
    subprocess.run(
        [
            str(INSTALLERS / "install-witness.sh"),
            "--apply",
            "--source-root",
            str(SOURCE_ROOT),
            "--release",
            "test-release",
            "--install-root",
            str(install_root),
            "--environment-file",
            str(environment),
            "--systemd-root",
            str(tmp_path / "systemd"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    current = install_root / "current"
    assert current.is_symlink()
    assert (current / "manifest.yml").is_file()
    assert not environment.exists()
    assert Path(f"{environment}.example").is_file()
    assert (
        tmp_path
        / "systemd"
        / "genomes-agentic-os-execution-fabric-witness-monitor.timer"
    ).is_file()

    environment.write_text(
        "\n".join(
            (
                "WITNESS_MODE=manual_fail_closed",
                "FABRIC_AUTO_FAILOVER=false",
                "FABRIC_ENABLE_PROMOTION=false",
                "",
            )
        ),
        encoding="utf-8",
    )
    activated = subprocess.run(
        [
            str(INSTALLERS / "activate-witness.sh"),
            "--apply",
            "--install-root",
            str(install_root),
            "--environment-file",
            str(environment),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert activated.returncode == 0, activated.stderr
    assert "no witness container will start" in activated.stdout


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
    assert "converge-policy-roles.sh" in script
    convergence = (INSTALLERS / "bin" / "converge-policy-roles.sh").read_text(
        encoding="utf-8"
    )
    assert "--force-recreate" in convergence
    assert '.approvedPolicyFingerprint==$digest' in convergence
    assert '.appliedPolicyFingerprint==$digest' in convergence
    assert '.status=="healthy"' in convergence
    assert "role_convergence_deferred" in script
    assert "fabric_policy_role_cohort_state" in script
    assert "resume_cohort_state" in script
    promotion = (INSTALLERS / "bin" / "promote.sh").read_text(encoding="utf-8")
    assert '"$script_dir/rotate-policy.sh" --resume' in promotion
    assert '"$script_dir/converge-policy-roles.sh" --verify' in promotion


def test_policy_rotation_runs_prepare_reload_commit_and_readback(
    tmp_path: Path,
) -> None:
    old_digest = "a" * 64
    new_digest = "b" * 64
    rotation_id = "00000000-0000-4000-8000-000000000001"
    state = tmp_path / "state"
    fake_bin = tmp_path / "bin"
    tokens = tmp_path / "tokens"
    deployment = tmp_path / "deployment"
    state.mkdir()
    fake_bin.mkdir()
    tokens.mkdir()
    deployment.mkdir()
    (deployment / "compose.genomesbox.yml").write_text(
        "services: {}\n", encoding="utf-8"
    )
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
    [ -f "$FAKE_STATE_DIR/roles-recreated" ] || exit 22
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
    if [ -f "$FAKE_STATE_DIR/roles-recreated" ]; then
      instance=new
    else
      instance=old
    fi
    printf '%s\\n' '{{"config":{{"appliedFingerprint":"'"$applied"'"}},
      "controlPlane":{{"databasePolicyFingerprint":"'"$applied"'",
      "leadership":{{"state":"active"}}}},
      "roleHealth":[
        {{"hostId":"genomesbox","role":"api","instanceId":"'"$instance"'-api","approvedPolicyFingerprint":"'"$applied"'","appliedPolicyFingerprint":"'"$applied"'","status":"healthy","lastSuccessfulTickAt":"2026-07-25T00:00:06Z"}},
        {{"hostId":"genomesbox","role":"observer","instanceId":"'"$instance"'-observer","approvedPolicyFingerprint":"'"$applied"'","appliedPolicyFingerprint":"'"$applied"'","status":"healthy","lastSuccessfulTickAt":"2026-07-25T00:00:06Z"}},
        {{"hostId":"genomesbox","role":"healer","instanceId":"'"$instance"'-healer","approvedPolicyFingerprint":"'"$applied"'","appliedPolicyFingerprint":"'"$applied"'","status":"healthy","lastSuccessfulTickAt":"2026-07-25T00:00:06Z"}},
        {{"hostId":"genomesbox","role":"scheduler","instanceId":"'"$instance"'-scheduler","approvedPolicyFingerprint":"'"$applied"'","appliedPolicyFingerprint":"'"$applied"'","status":"healthy","lastSuccessfulTickAt":"2026-07-25T00:00:06Z"}}]}}'
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
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        """#!/bin/sh
set -eu
operation=
role=
for argument in "$@"; do
  case "$argument" in
    ps|up) operation=$argument ;;
    control-plane|observer|healer|scheduler) role=$argument ;;
  esac
done
case "$operation" in
  ps)
    if [ -f "$FAKE_STATE_DIR/roles-recreated" ]; then prefix=new; else prefix=old; fi
    printf '%s-%s\n' "$prefix" "$role"
    ;;
  up) : >"$FAKE_STATE_DIR/roles-recreated" ;;
  *) exit 64 ;;
esac
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
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
                "FABRIC_DEPLOYMENT_ROLE=primary",
                f"FABRIC_DEPLOYMENT_DIR={deployment}",
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
    recreate = json.loads(
        Path(payload["roleRecreateReceipt"]).read_text(encoding="utf-8")
    )
    verify = json.loads(
        Path(payload["roleVerifyReceipt"]).read_text(encoding="utf-8")
    )
    assert recreate["containersBefore"]["control-plane"] == "old-control-plane"
    assert recreate["containersAfter"]["control-plane"] == "new-control-plane"
    assert recreate["instancesBefore"]["api"] == "old-api"
    assert next(
        row for row in recreate["roleHealth"] if row["role"] == "api"
    )["instanceId"] == "new-api"
    assert {row["role"] for row in verify["roleHealth"]} == {
        "api",
        "observer",
        "healer",
        "scheduler",
    }
    assert (state / "committed").is_file()
    assert not (state / "policy-rotation.pending.json").exists()


def test_policy_role_convergence_fails_closed_on_one_mismatched_role(
    tmp_path: Path,
) -> None:
    expected = "b" * 64
    wrong = "c" * 64
    state = tmp_path / "state"
    fake_bin = tmp_path / "bin"
    deployment = tmp_path / "deployment"
    token = tmp_path / "api-token"
    state.mkdir()
    fake_bin.mkdir()
    deployment.mkdir()
    token.write_text("test-token\n", encoding="utf-8")
    (deployment / "compose.bigmac.yml").write_text(
        "services: {}\n", encoding="utf-8"
    )
    _write_executable(
        fake_bin / "docker",
        """#!/bin/sh
set -eu
operation=
role=
for argument in "$@"; do
  case "$argument" in
    ps|up) operation=$argument ;;
    control-plane|observer|healer|scheduler) role=$argument ;;
  esac
done
case "$operation" in
  ps)
    if [ -f "$FAKE_STATE_DIR/recreated" ]; then prefix=new; else prefix=old; fi
    printf '%s-%s\n' "$prefix" "$role"
    ;;
  up) : >"$FAKE_STATE_DIR/recreated" ;;
  *) exit 64 ;;
esac
""",
    )
    role_health = [
        {
            "hostId": "genomesbox",
            "role": role,
            "instanceId": f"old-{role}",
            "approvedPolicyFingerprint": wrong if role == "observer" else expected,
            "appliedPolicyFingerprint": expected,
            "status": "unhealthy" if role == "observer" else "healthy",
            "lastSuccessfulTickAt": "2026-07-25T00:00:06Z",
        }
        for role in ("api", "observer", "healer", "scheduler")
    ]
    _write_executable(
        fake_bin / "curl",
        "#!/bin/sh\nset -eu\nprintf '%s\\n' "
        + repr(json.dumps({"roleHealth": role_health}))
        + "\n",
    )
    runtime = tmp_path / "runtime.env"
    runtime.write_text(
        "\n".join(
            (
                f"FABRIC_OS_ROOT={tmp_path}",
                f"FABRIC_RUNTIME_STATE_DIR={state}",
                "FABRIC_API_BASE=http://control",
                f"FABRIC_API_TOKEN_FILE={token}",
                "FABRIC_HOST_ID=genomesbox",
                "FABRIC_DEPLOYMENT_ROLE=standby",
                f"FABRIC_DEPLOYMENT_DIR={deployment}",
                "FABRIC_POLICY_CONVERGENCE_ATTEMPTS=1",
                f"FAKE_STATE_DIR={state}",
                "",
            )
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            str(INSTALLERS / "bin" / "converge-policy-roles.sh"),
            "--recreate",
            expected,
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
    assert result.returncode == 75
    assert "did not converge" in result.stderr
    assert not list(state.glob("policy-role-convergence-*.json"))

    _write_executable(
        fake_bin / "curl",
        "#!/bin/sh\nset -eu\nprintf '%s\\n' '{}'\n",
    )
    missing_schema = subprocess.run(
        [
            str(INSTALLERS / "bin" / "converge-policy-roles.sh"),
            "--verify",
            expected,
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
    assert missing_schema.returncode == 69
    assert "upgrade the control-plane image" in missing_schema.stderr


def test_policy_role_cohort_state_treats_crash_loop_as_partial(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    runtime = tmp_path / "runtime.env"
    compose_file = tmp_path / "compose.bigmac.yml"
    runtime.write_text("FABRIC_HOST_ID=bigmac\n", encoding="utf-8")
    compose_file.write_text("services: {}\n", encoding="utf-8")
    _write_executable(
        fake_bin / "docker",
        """#!/bin/sh
set -eu
all=false
running=false
role=
for argument in "$@"; do
  case "$argument" in
    -a) all=true ;;
    --status) running=true ;;
    control-plane|observer|healer|scheduler) role=$argument ;;
  esac
done
case "$COHORT_MODE" in
  dormant) exit 0 ;;
  crashing) [ "$all" = true ] && printf 'stopped-%s\\n' "$role" ;;
  active) printf 'running-%s\\n' "$role" ;;
  partial)
    if [ "$all" = true ] || [ "$role" = control-plane ]; then
      printf 'mixed-%s\\n' "$role"
    fi
    ;;
  *) exit 64 ;;
esac
exit 0
""",
    )
    command = """
. "$1"
FABRIC_RUNTIME_ENV_FILE=$2
export FABRIC_RUNTIME_ENV_FILE
fabric_policy_role_cohort_state "$3" promoted
"""
    for mode, expected in (
        ("dormant", "dormant"),
        ("crashing", "partial"),
        ("active", "active"),
        ("partial", "partial"),
    ):
        result = subprocess.run(
            [
                "sh",
                "-c",
                command,
                "cohort-state-test",
                str(INSTALLERS / "bin/_lib.sh"),
                str(runtime),
                str(compose_file),
            ],
            check=False,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "COHORT_MODE": mode,
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
            },
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == expected


def test_policy_role_recreate_recovers_when_initial_api_is_down(
    tmp_path: Path,
) -> None:
    expected = "b" * 64
    state = tmp_path / "state"
    fake_bin = tmp_path / "bin"
    deployment = tmp_path / "deployment"
    token = tmp_path / "api-token"
    state.mkdir()
    fake_bin.mkdir()
    deployment.mkdir()
    token.write_text("test-token\n", encoding="utf-8")
    (deployment / "compose.genomesbox.yml").write_text(
        "services: {}\n", encoding="utf-8"
    )
    _write_executable(
        fake_bin / "docker",
        """#!/bin/sh
set -eu
operation=
role=
for argument in "$@"; do
  case "$argument" in
    ps|up) operation=$argument ;;
    control-plane|observer|healer|scheduler) role=$argument ;;
  esac
done
case "$operation" in
  ps)
    if [ -f "$FAKE_STATE_DIR/recreated" ]; then prefix=new; else prefix=old; fi
    printf '%s-%s\\n' "$prefix" "$role"
    ;;
  up) : >"$FAKE_STATE_DIR/recreated" ;;
  *) exit 64 ;;
esac
""",
    )
    role_health = [
        {
            "hostId": "genomesbox",
            "role": role,
            "instanceId": f"new-{role}",
            "approvedPolicyFingerprint": expected,
            "appliedPolicyFingerprint": expected,
            "status": "healthy",
            "lastSuccessfulTickAt": "2026-07-25T00:00:06Z",
        }
        for role in ("api", "observer", "healer", "scheduler")
    ]
    _write_executable(
        fake_bin / "curl",
        "#!/bin/sh\nset -eu\n"
        "[ -f \"$FAKE_STATE_DIR/recreated\" ] || exit 22\n"
        "printf '%s\\n' " + repr(json.dumps({"roleHealth": role_health})) + "\n",
    )
    runtime = tmp_path / "runtime.env"
    runtime.write_text(
        "\n".join(
            (
                f"FABRIC_OS_ROOT={tmp_path}",
                f"FABRIC_RUNTIME_STATE_DIR={state}",
                "FABRIC_API_BASE=http://control",
                f"FABRIC_API_TOKEN_FILE={token}",
                "FABRIC_HOST_ID=genomesbox",
                "FABRIC_DEPLOYMENT_ROLE=primary",
                f"FABRIC_DEPLOYMENT_DIR={deployment}",
                "FABRIC_POLICY_CONVERGENCE_ATTEMPTS=1",
                f"FAKE_STATE_DIR={state}",
                "",
            )
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            str(INSTALLERS / "bin" / "converge-policy-roles.sh"),
            "--recreate",
            expected,
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
    receipt = json.loads(Path(result.stdout.strip()).read_text(encoding="utf-8"))
    assert receipt["instancesBefore"] == {}
    assert receipt["containersAfter"]["control-plane"] == "new-control-plane"


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


def test_personal_fallback_watchdog_alerts_when_primary_ready_is_false(
    tmp_path: Path,
) -> None:
    os_root = tmp_path / "os"
    notifier = os_root / "harness/bin/agentic-os-notify"
    receipt = tmp_path / "notification.txt"
    _write_executable(
        notifier,
        """#!/definitely/missing-python
import os
from pathlib import Path
import sys
Path(os.environ["NOTIFY_RECEIPT"]).write_text(
    f"selected={os.environ.get('SELECTED_INTERPRETER')} " + " ".join(sys.argv[1:]) + "\\n"
)
""",
    )
    fake_cli = tmp_path / "agentic-os"
    _write_executable(
        fake_cli,
        """#!/bin/sh
case "$3" in
  status) printf '%s\n' '{"status":"standby"}' ;;
  probe) printf '%s\n' '{"status":"active","primary_ready":false}' ;;
  *) exit 64 ;;
esac
""",
    )
    runtime = tmp_path / "runtime.env"
    runtime.write_text(
        "\n".join(
            (
                f"FABRIC_OS_ROOT={os_root}",
                f"FABRIC_AGENTIC_OS_CLI={fake_cli}",
                f"FABRIC_AGENTIC_OS_PYTHON={sys.executable}",
                f"FABRIC_RUNTIME_STATE_DIR={tmp_path / 'state'}",
                "",
            )
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(INSTALLERS / "bin" / "personal-fallback-watchdog.sh")],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "FABRIC_RUNTIME_ENV_FILE": str(runtime),
            "NOTIFY_RECEIPT": str(receipt),
        },
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["primary_ready"] is False
    notification = receipt.read_text(encoding="utf-8")
    assert "selected=None" in notification
    assert "--level critical" in notification
    assert "Execution Fabric local fallback ACTIVE" in notification
    assert "execution-fabric-personal-fallback-active" in notification


def test_fabric_notify_resolves_absolute_named_and_cli_sibling_python(
    tmp_path: Path,
) -> None:
    lib = INSTALLERS / "bin" / "_lib.sh"
    for mode in ("absolute", "name", "cli_sibling"):
        case_root = tmp_path / mode
        os_root = case_root / "os"
        receipt = case_root / "receipt.txt"
        notifier = os_root / "harness/bin/agentic-os-notify"
        _write_executable(
            notifier,
            """#!/definitely/missing-python
import os
from pathlib import Path
import sys
Path(os.environ["NOTIFY_RECEIPT"]).write_text(
    f"selected={os.environ['SELECTED_INTERPRETER']} " + " ".join(sys.argv[1:]) + "\\n"
)
""",
        )
        fake_bin = case_root / "bin"
        wrapper = fake_bin / ("governed-python" if mode == "name" else "python")
        _write_executable(
            wrapper,
            """#!/bin/sh
export SELECTED_INTERPRETER="$INTERPRETER_MARKER"
exec "$REAL_PYTHON" "$@"
""",
        )
        cli = fake_bin / "agentic-os"
        worker_python = "missing-python"
        agentic_python = ""
        if mode == "absolute":
            agentic_python = str(wrapper)
        elif mode == "name":
            worker_python = "governed-python"

        result = subprocess.run(
            [
                "/bin/sh",
                "-c",
                f'. "{lib}"; fabric_notify critical "Fallback" "Primary down" "fallback-key"',
            ],
            check=False,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "FABRIC_OS_ROOT": str(os_root),
                "FABRIC_AGENTIC_OS_CLI": str(cli),
                "FABRIC_AGENTIC_OS_PYTHON": agentic_python,
                "FABRIC_WORKER_PYTHON": worker_python,
                "NOTIFY_RECEIPT": str(receipt),
                "INTERPRETER_MARKER": mode,
                "REAL_PYTHON": sys.executable,
            },
        )

        assert result.returncode == 0, result.stderr
        notification = receipt.read_text(encoding="utf-8")
        assert f"selected={mode}" in notification
        assert "--level critical" in notification
        assert "--dedupe-key fallback-key" in notification


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
    assert "installers/bin/run-primary.sh start" in primary
    primary_runner = (INSTALLERS / "bin/run-primary.sh").read_text(
        encoding="utf-8"
    )
    assert '--profile primary' in primary_runner
    assert '--profile standalone-primary' in primary_runner


def test_standalone_primary_runner_bootstraps_once_then_waits_before_primary(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_log = tmp_path / "docker.log"
    runtime_env = tmp_path / "runtime.env"
    runtime_env.write_text(
        "\n".join(
            (
                f"FABRIC_OS_ROOT={tmp_path / 'os'}",
                f"FABRIC_RUNTIME_STATE_DIR={state}",
                f"FABRIC_DEPLOYMENT_DIR={tmp_path / 'deploy'}",
                "FABRIC_WITNESS_MODE=standalone_primary",
                "FABRIC_STANDALONE_WITNESS_BOOTSTRAP_ONCE=false",
                "FABRIC_LEADERSHIP_API_BASE=http://witness",
                "FABRIC_CLUSTER_ID=test-cluster",
                "",
            )
        ),
        encoding="utf-8",
    )
    _write_executable(
        fake_bin / "install",
        """#!/bin/sh
for argument in "$@"; do target=$argument; done
mkdir -p "$target"
""",
    )
    _write_executable(
        fake_bin / "docker",
        """#!/bin/sh
printf 'bootstrap=%s %s\n' "${FABRIC_STANDALONE_WITNESS_BOOTSTRAP_ONCE:-unset}" "$*" >>"$DOCKER_LOG"
case " $* " in
  *" leadership-witness "*)
    if [ "${FABRIC_STANDALONE_WITNESS_BOOTSTRAP_ONCE:-false}" = true ]; then
      mkdir -p "$FABRIC_RUNTIME_STATE_DIR/standalone-witness"
      printf 'database\n' >"$FABRIC_RUNTIME_STATE_DIR/standalone-witness/witness.sqlite3"
      printf 'sentinel\n' >"$FABRIC_RUNTIME_STATE_DIR/standalone-witness/witness.sqlite3.initialized"
    fi
    ;;
esac
""",
    )
    _write_executable(
        fake_bin / "curl",
        """#!/bin/sh
[ -s "$FABRIC_RUNTIME_STATE_DIR/standalone-witness/witness.sqlite3" ]
[ -s "$FABRIC_RUNTIME_STATE_DIR/standalone-witness/witness.sqlite3.initialized" ]
""",
    )
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "DOCKER_LOG": str(docker_log),
        "FABRIC_RUNTIME_ENV_FILE": str(runtime_env),
    }
    subprocess.run(
        ["sh", str(INSTALLERS / "bin/run-primary.sh"), "start"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    lines = docker_log.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("bootstrap=true ")
    assert "up -d leadership-witness" in lines[0]
    assert lines[1].startswith("bootstrap=false ")
    assert "--force-recreate leadership-witness" in lines[1]
    assert lines[2].startswith("bootstrap=false ")
    assert "--profile primary --profile standalone-primary up" in lines[2]
    assert (state / "standalone-witness.bootstrap-complete").is_file()

    docker_log.write_text("", encoding="utf-8")
    subprocess.run(
        ["sh", str(INSTALLERS / "bin/run-primary.sh"), "start"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    assert "bootstrap=true" not in docker_log.read_text(encoding="utf-8")


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
            INSTALLERS / "install-witness.sh",
            INSTALLERS / "activate-linux.sh",
            INSTALLERS / "activate-macos.sh",
            INSTALLERS / "activate-witness.sh",
        ]
    )
    scripts.extend(sorted((DEPLOY / "witness/bin").glob("*.sh")))
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
    shutil.copy2(INSTALLERS / "bin/_lib.sh", installer / "bin/_lib.sh")
    runtime_state = tmp_path / "runtime-state"
    runtime_env = tmp_path / "runtime.env"
    runtime_env.write_text(
        "\n".join(
            (
                f"FABRIC_OS_ROOT={tmp_path}",
                f"FABRIC_RUNTIME_STATE_DIR={runtime_state}",
                "FABRIC_WITNESS_MODE=independent",
                "",
            )
        ),
        encoding="utf-8",
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
        "FABRIC_RUNTIME_ENV_FILE": str(runtime_env),
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

    runtime_env.write_text(
        "\n".join(
            (
                f"FABRIC_OS_ROOT={tmp_path}",
                f"FABRIC_RUNTIME_STATE_DIR={runtime_state}",
                "FABRIC_WITNESS_MODE=standalone_primary",
                "",
            )
        ),
        encoding="utf-8",
    )
    activation_log.write_text("", encoding="utf-8")
    subprocess.run(
        ["sh", str(installer / "activate-linux.sh"), "--apply"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    standalone_lines = activation_log.read_text(encoding="utf-8").splitlines()
    assert any(
        "systemctl disable --now "
        "genomes-agentic-os-execution-fabric-artifact-replication.timer" in line
        for line in standalone_lines
    )
    assert not any(
        line.startswith("systemctl enable ")
        and "artifact-replication.timer" in line
        for line in standalone_lines
    )
    assert not any(
        line.startswith("systemctl start ")
        and "artifact-replication.timer" in line
        for line in standalone_lines
    )


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


def test_macos_personal_activation_starts_only_client_plane_after_preflight(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    installer = tmp_path / "installer"
    installer.mkdir()
    shutil.copy2(INSTALLERS / "activate-macos.sh", installer / "activate-macos.sh")
    activation_log = tmp_path / "activation.log"
    _write_executable(
        installer / "bin/preflight-personal-client.sh",
        "#!/bin/sh\nprintf 'preflight personal-client\\n' >>\"$ACTIVATION_LOG\"\n",
    )
    _write_executable(
        installer / "bin/preflight.sh",
        "#!/bin/sh\nprintf 'unexpected standby preflight\\n' >>\"$ACTIVATION_LOG\"\nexit 1\n",
    )
    fake_bin = tmp_path / "bin"
    _write_executable(fake_bin / "uname", "#!/bin/sh\nprintf 'Darwin\\n'\n")
    _write_executable(fake_bin / "id", "#!/bin/sh\nprintf '501\\n'\n")
    _write_executable(
        fake_bin / "launchctl",
        """#!/bin/sh
case "$1" in
  print) exit 1 ;;
  bootstrap) printf 'bootstrap %s\n' "$(basename "$3" .plist)" >>"$ACTIVATION_LOG" ;;
  *) exit 64 ;;
esac
""",
    )
    launch_agents = home / "Library/LaunchAgents"
    launch_agents.mkdir(parents=True)
    for suffix in ("worker", "alarm-dispatcher", "personal-fallback"):
        (launch_agents / f"com.genomes.agentic-os.execution-fabric.{suffix}.plist").write_text(
            "<plist/>", encoding="utf-8"
        )

    result = subprocess.run(
        [
            "sh",
            str(installer / "activate-macos.sh"),
            "--apply",
            "--personal-fallback",
        ],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "ACTIVATION_LOG": str(activation_log),
            "HOME": str(home),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
        },
    )

    assert result.returncode == 0, result.stderr
    assert activation_log.read_text(encoding="utf-8").splitlines() == [
        "preflight personal-client",
        "bootstrap com.genomes.agentic-os.execution-fabric.worker",
        "bootstrap com.genomes.agentic-os.execution-fabric.alarm-dispatcher",
        "bootstrap com.genomes.agentic-os.execution-fabric.personal-fallback",
    ]


def test_personal_client_preflight_uses_only_scoped_client_credentials() -> None:
    preflight = (INSTALLERS / "bin/preflight-personal-client.sh").read_text(
        encoding="utf-8"
    )
    assert "AGENTIC_OS_EXECUTION_FABRIC_WORKER_TOKEN_FILE" in preflight
    assert "FABRIC_ALARM_DISPATCHER_TOKEN_FILE" in preflight
    assert "FABRIC_WORKER_BOOTSTRAP_CREDENTIALS_FILE" not in preflight
    assert "FABRIC_ALARM_DISPATCHER_CREDENTIALS_FILE" not in preflight
    assert "postgres-password" not in preflight
    assert "FABRIC_ENABLE_PROMOTION" in preflight
    assert "--validate-routes" in preflight


def test_personal_client_preflight_accepts_scoped_worker_and_alarm_clients(
    tmp_path: Path,
) -> None:
    root = tmp_path / "os"
    notifier = root / "harness/bin/agentic-os-notify"
    _write_executable(notifier, "#!/bin/sh\nexit 0\n")
    fake_bin = tmp_path / "bin"
    cli = fake_bin / "agentic-os"
    config_show = tmp_path / "config-show.json"
    config_show.write_text(
        json.dumps(
            {
                "effective": {
                    "execution_fabric": {
                        "transport": {
                            "mode": "remote_with_local_fallback",
                            "control_plane_url": "http://100.117.29.53:3180",
                        },
                        "admission": {"host_limits": {"bigmac": 4}},
                        "queues": [
                            {
                                "id": "pr_reviews",
                                "enabled": True,
                                "worker_pool": "pr_reviewers",
                            }
                        ],
                        "worker_pools": [
                            {
                                "id": "pr_reviewers",
                                "enabled": True,
                                "queues": ["pr_reviews"],
                                "capacity": {"max_tasks_per_worker": 2},
                            }
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    _write_executable(
        cli,
        """#!/bin/sh
case " $* " in
  *" runtime config show "*) cat "$CONFIG_SHOW" ;;
  *" runtime fallback status "*) printf '{"status":"standby"}\n' ;;
  *) exit 64 ;;
esac
""",
    )
    _write_executable(
        fake_bin / "curl",
        "#!/bin/sh\nprintf '{\"state\":\"routable\",\"leader\":\"genomesbox\"}\\n'\n",
    )
    worker_executable = fake_bin / "worker"
    _write_executable(worker_executable, "#!/bin/sh\nexit 0\n")
    worker_token = tmp_path / "worker-token"
    alarm_token = tmp_path / "alarm-token"
    worker_token.write_text("w" * 48, encoding="utf-8")
    alarm_token.write_text("a" * 48, encoding="utf-8")
    runtime_env = tmp_path / "runtime.env"
    runtime_env.write_text(
        "\n".join(
            (
                f"FABRIC_OS_ROOT={root}",
                f"FABRIC_RUNTIME_STATE_DIR={tmp_path / 'state'}",
                "FABRIC_HOST_ID=bigmac",
                "FABRIC_PRIMARY_HOST_ID=genomesbox",
                "FABRIC_STANDBY_HOST_ID=bigmac",
                "FABRIC_AUTO_FAILOVER=false",
                "FABRIC_ENABLE_PROMOTION=false",
                f"FABRIC_AGENTIC_OS_CLI={cli}",
                "FABRIC_GATEWAY_API_BASE=http://100.117.29.53:3181",
                "FABRIC_WORKER_ID=bigmac-pr-reviewer-1",
                "FABRIC_WORKER_BOOTSTRAP_ID=bigmac-pr-reviewer-1",
                "FABRIC_WORKER_POOL_ID=pr_reviewers",
                "FABRIC_WORKER_ACCEPTED_QUEUES=pr_reviews",
                "FABRIC_WORKER_CAPABILITIES=pr_review",
                "FABRIC_WORKER_MAX_CONCURRENCY=2",
                f"AGENTIC_OS_EXECUTION_FABRIC_WORKER_TOKEN_FILE={worker_token}",
                f"FABRIC_ALARM_DISPATCHER_TOKEN_FILE={alarm_token}",
                "FABRIC_ALARM_DISPATCHER_CONSUMER_ID=bigmac-agentic-os-notifier",
                "FABRIC_ALARM_DISPATCHER_SOURCE=agentic-os-notify",
                f"FABRIC_WORKER_EXECUTABLE={worker_executable}",
                f"FABRIC_WORKER_PYTHON={sys.executable}",
                "",
            )
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["sh", str(INSTALLERS / "bin/preflight-personal-client.sh")],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "CONFIG_SHOW": str(config_show),
            "FABRIC_RUNTIME_ENV_FILE": str(runtime_env),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
        },
    )

    assert result.returncode == 0, result.stderr
    assert "personal client preflight passed" in result.stdout

    runtime_env.write_text(
        runtime_env.read_text(encoding="utf-8").replace(
            "FABRIC_WORKER_MAX_CONCURRENCY=2",
            "FABRIC_WORKER_MAX_CONCURRENCY=1",
        ),
        encoding="utf-8",
    )
    undersized = subprocess.run(
        ["sh", str(INSTALLERS / "bin/preflight-personal-client.sh")],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "CONFIG_SHOW": str(config_show),
            "FABRIC_RUNTIME_ENV_FILE": str(runtime_env),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
        },
    )
    assert undersized.returncode == 78
    assert "conflicts with canonical policy" in undersized.stderr


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
    runtime_env = (DEPLOY / "runtime.env.example").read_text(encoding="utf-8")
    for variable in (
        "FABRIC_WORKER_ID",
        "FABRIC_WORKER_BOOTSTRAP_ID",
        "FABRIC_WORKER_POOL_ID",
        "FABRIC_WORKER_ACCEPTED_QUEUES",
        "FABRIC_WORKER_CAPABILITIES",
        "FABRIC_WORKER_MAX_CONCURRENCY",
        "AGENTIC_OS_EXECUTION_FABRIC_WORKER_TOKEN_FILE",
    ):
        assert f"{variable}=" in runtime_env
        assert variable in preflight
    assert "$credential.token==$token" in preflight


def test_compose_helper_preserves_runtime_and_deployment_paths_with_spaces(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    argument_log = tmp_path / "docker-arguments.log"
    _write_executable(
        fake_bin / "docker",
        """#!/bin/sh
for argument in "$@"; do
  printf '%s\n' "$argument" >>"$DOCKER_ARGUMENT_LOG"
done
""",
    )
    runtime_env = tmp_path / "Application Support/runtime.env"
    compose_file = tmp_path / "Application Support/compose.bigmac.yml"
    runtime_env.parent.mkdir(parents=True)
    runtime_env.write_text("FABRIC_HOST_ID=bigmac\n", encoding="utf-8")
    compose_file.write_text("services: {}\n", encoding="utf-8")
    command = """
. "$1"
FABRIC_RUNTIME_ENV_FILE=$2
export FABRIC_RUNTIME_ENV_FILE
fabric_compose "$3" --profile standby ps --status running
"""
    subprocess.run(
        [
            "sh",
            "-c",
            command,
            "fabric-compose-test",
            str(INSTALLERS / "bin/_lib.sh"),
            str(runtime_env),
            str(compose_file),
        ],
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "DOCKER_ARGUMENT_LOG": str(argument_log),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
        },
    )
    assert argument_log.read_text(encoding="utf-8").splitlines() == [
        "compose",
        "--env-file",
        str(runtime_env),
        "-f",
        str(compose_file),
        "--profile",
        "standby",
        "ps",
        "--status",
        "running",
    ]


def test_all_compose_command_scripts_use_argument_safe_invocation() -> None:
    affected = (
        "activate-receipt.sh",
        "candidate-reporter-health.sh",
        "enable-postgres-durable-primary.sh",
        "failback.sh",
        "promote.sh",
        "reseed-postgres-standby.sh",
    )
    for name in affected:
        script = (INSTALLERS / "bin" / name).read_text(encoding="utf-8")
        assert 'compose="docker compose' not in script
        assert re.search(r"(?m)^\$compose(?:\s|$)", script) is None
        assert "fabric_compose" in script


def test_failback_and_reseed_share_canonical_target_slot_contract() -> None:
    library = (INSTALLERS / "bin/_lib.sh").read_text(encoding="utf-8")
    failback = (INSTALLERS / "bin/failback.sh").read_text(encoding="utf-8")
    reseed = (
        INSTALLERS / "bin/reseed-postgres-standby.sh"
    ).read_text(encoding="utf-8")
    activation = (
        INSTALLERS / "bin/activate-receipt.sh"
    ).read_text(encoding="utf-8")
    assert "primary) printf '%s\\n' genomesbox_fabric" in library
    assert "standby) printf '%s\\n' bigmac_fabric" in library
    assert "fabric_failback_target" not in failback
    assert "target_slot=$(fabric_replication_slot primary)" in failback
    assert "slot=$(fabric_replication_slot primary)" in reseed
    assert "slot=$(fabric_replication_slot standby)" in reseed
    assert "standby_slot=$(fabric_replication_slot standby)" in activation


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
    images = {
        name: f"example.invalid/{name.replace('_', '-')}@sha256:{digest}"
        for name in (
            "control_plane",
            "leadership_witness",
            "worker",
            "postgres",
            "valkey",
            "minio",
            "minio_client",
        )
    }
    image_lock = tmp_path / "execution-fabric-image-lock.json"
    image_lock.write_text(
        json.dumps(
            {
                "schema_version": "execution-fabric-image-lock/v1",
                "release_version": "test-release",
                "images": images,
            }
        ),
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
    assert json.loads(
        (output / "execution-fabric-image-lock.json").read_text(encoding="utf-8")
    )["images"] == images
    materialized = (output / "images.lock.env").read_text(encoding="utf-8")
    for variable in (
        "FABRIC_CONTROL_PLANE_IMAGE",
        "FABRIC_WITNESS_IMAGE",
        "FABRIC_WORKER_IMAGE",
        "FABRIC_POSTGRES_IMAGE",
        "FABRIC_VALKEY_IMAGE",
        "FABRIC_MINIO_IMAGE",
        "FABRIC_MINIO_CLIENT_IMAGE",
    ):
        assert f"{variable}=" in materialized
    assert "secrets_included=false" in (output / "RELEASE").read_text(encoding="utf-8")

    (output / "images.lock.env").write_text(
        materialized.replace("FABRIC_WITNESS_IMAGE=", "FABRIC_WITNESS_IMAGE=mutable:"),
        encoding="utf-8",
    )
    invalid = subprocess.run(
        ["sh", str(INSTALLERS / "bin/validate-emergency-bundle.sh"), str(output)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert invalid.returncode == 78
    assert "does not match the canonical JSON lock" in invalid.stderr


def test_image_lock_materializer_rejects_missing_or_mutable_images(
    tmp_path: Path,
) -> None:
    digest = "2" * 64
    lock = {
        "schema_version": "execution-fabric-image-lock/v1",
        "release_version": "test-release",
        "images": {
            name: f"example.invalid/{name.replace('_', '-')}@sha256:{digest}"
            for name in (
                "control_plane",
                "leadership_witness",
                "worker",
                "postgres",
                "valkey",
                "minio",
                "minio_client",
            )
        },
    }
    lock_path = tmp_path / "lock.json"
    command = [
        "sh",
        str(INSTALLERS / "bin/materialize-image-lock.sh"),
        str(lock_path),
    ]
    lock["images"].pop("leadership_witness")
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    missing = subprocess.run(command, check=False, capture_output=True, text=True)
    assert missing.returncode != 0

    lock["images"]["leadership_witness"] = "example.invalid/witness:latest"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    mutable = subprocess.run(command, check=False, capture_output=True, text=True)
    assert mutable.returncode != 0


def test_documentation_exposes_the_implemented_witness_and_activation_boundary() -> None:
    readme = (DEPLOY / "README.md").read_text(encoding="utf-8")
    normalized = " ".join(readme.split())
    assert "/api/v1/admin/leadership/*" in readme
    assert "canonical provider-neutral deployment" in normalized
    assert "singleton SQLite authority" in normalized
    assert "cloud-provider deployment dependency" in normalized
    assert "manual_fail_closed" in normalized
    assert "Source availability does not activate the witness" in normalized
    assert "operator prerequisites" in normalized
    assert re.search(r"Failback is always manual", readme)


def test_standalone_primary_is_explicit_non_ha_and_uses_installed_canonical_mounts() -> None:
    primary = _yaml(DEPLOY / "compose.genomesbox.yml")
    witness = primary["services"]["leadership-witness"]
    assert witness["profiles"] == ["standalone-primary"]
    assert witness["environment"]["WITNESS_STANDALONE_PRIMARY_HOST_ID"] == (
        "${FABRIC_PRIMARY_HOST_ID:?set primary host identity}"
    )
    assert witness["environment"]["WITNESS_ALLOW_DEGRADED_PRIMARY"] == "false"
    assert witness["volumes"] == [
        "${FABRIC_RUNTIME_STATE_DIR:?set runtime state directory}/standalone-witness:"
        "/var/lib/execution-fabric-witness"
    ]
    assert "standalone-witness-data" not in primary.get("volumes", {})

    for name in ("compose.genomesbox.yml", "compose.bigmac.yml"):
        text = (DEPLOY / name).read_text(encoding="utf-8")
        assert "../../harness/config/execution-fabric.yml" not in text
        assert "../../schemas/execution-fabric.schema.json" not in text
        assert "/harness/config:/etc/agentic-os/policy-bundle/config:ro" in text
        assert "/harness/schemas:/etc/agentic-os/policy-bundle/schemas:ro" in text
        assert "/harness:/etc/agentic-os/policy-bundle:ro" not in text
        assert "/policy-bundle/config/execution-fabric.yml" in text
        assert "/policy-bundle/schemas/execution-fabric.schema.json" in text

    preflight = (INSTALLERS / "bin/preflight.sh").read_text(encoding="utf-8")
    assert "FABRIC_MINIO_CLIENT_IMAGE" in preflight
    assert "standalone_primary requires automatic failover" in preflight
    assert ".effective.execution_fabric.standalone_primary.enabled==true" in preflight
    assert ".effective.execution_fabric.standalone_primary.host_id==$host" in preflight
    assert "keep FABRIC_STANDALONE_WITNESS_BOOTSTRAP_ONCE=false" in preflight
    assert "standalone-witness.bootstrap-complete" in preflight

    primary_runner = (INSTALLERS / "bin/run-primary.sh").read_text(
        encoding="utf-8"
    )
    assert "FABRIC_STANDALONE_WITNESS_BOOTSTRAP_ONCE=true" in primary_runner
    assert "standalone-witness.bootstrap-complete" in primary_runner
    assert "wait_for_standalone_witness" in primary_runner
    assert "--force-recreate leadership-witness" in primary_runner

    activation = (INSTALLERS / "activate-linux.sh").read_text(encoding="utf-8")
    assert '"${FABRIC_WITNESS_MODE:-independent}" != standalone_primary' in activation
    assert "systemctl disable --now" in activation

    rotation = (INSTALLERS / "bin/rotate-policy.sh").read_text(encoding="utf-8")
    assert 'FABRIC_WITNESS_MODE:-independent}" = standalone_primary' in rotation
    assert '.authorityMode=="standalone_primary"' in rotation
    assert "standalone-primary policy maintenance must run on its exact primary host" in rotation
