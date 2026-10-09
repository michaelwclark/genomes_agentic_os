#!/usr/bin/env python3
"""Qualify cold recovery in one disposable PostgreSQL container, then remove it.

Provision the locked Python environment, build both Fabric services and pull the
exact IMAGE first. This runner never pulls an image or touches an installed
Fabric. Exit 0 requires the real database acceptance receipt and verified
container teardown. Artifacts are private; credentials are deleted on exit.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import time
from urllib.parse import quote
from uuid import uuid4

IMAGE = "docker.io/library/postgres@sha256:742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193"
LABEL = "io.genomes.fabric.cold-qualification"
CONTROL = "services/execution-fabric-control-plane"
WITNESS = "services/execution-fabric-leadership-witness"


def command(argv, timeout=30):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return subprocess.CompletedProcess(argv, 124, "", "bounded local actor unavailable")


def canonical_directory(value):
    path = Path(value)
    if not path.is_absolute() or path != path.resolve(strict=True):
        raise ValueError("a canonical absolute directory is required")
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("symlink directories are refused")
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise ValueError("directory must be owned and not group/world writable")
    return path


def source_root(value):
    root = canonical_directory(value)
    for relative in ("pyproject.toml", CONTROL + "/package.json", WITNESS + "/package.json",
                     CONTROL + "/dist/src/cold-recovery-main.js", WITNESS + "/dist/src/cold-recovery-main.js"):
        file = root / relative
        info = file.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022:
            raise ValueError("owned built source files are required")
        if file != file.resolve(strict=True):
            raise ValueError("source actor paths must not traverse symlinks")
    # A standard virtualenv interpreter is a symlink to its provisioned Python.
    if not (root / ".venv/bin/python").is_file() or not os.access(root / ".venv/bin/python", os.X_OK):
        raise ValueError("the locked repository Python environment is required")
    return root


def private_write(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as file:
        file.write(data)
        file.flush()
        os.fsync(file.fileno())


def document(path, value):
    private_write(path, json.dumps(value, sort_keys=True, indent=2) + "\n")


def inspected(value):
    if value.returncode != 0:
        raise ValueError("Docker inspection unavailable")
    data = json.loads(value.stdout)
    if not isinstance(data, dict):
        raise ValueError("Docker inspection shape differs")
    return data


def owned_container(data, name, token, cid=None):
    identity = data.get("Id", "")
    if (not re.fullmatch(r"[0-9a-f]{64}", identity) or (cid is not None and identity != cid)
            or data.get("Name") != "/" + name
            or data.get("Config", {}).get("Labels", {}).get(LABEL) != token):
        raise ValueError("exact disposable container ownership differs")
    return identity


def validate_container(data, name, token, cid, image_id):
    owned_container(data, name, token, cid)
    config = data.get("HostConfig", {})
    if (data.get("Image") != image_id or config.get("RestartPolicy", {}).get("Name") != "no"
            or config.get("Binds") or config.get("Memory") != 512 * 1024 * 1024
            or config.get("NanoCpus") != 1_000_000_000
            or any(mount.get("Type") == "bind" for mount in data.get("Mounts", []))):
        raise ValueError("disposable container image/resources/mounts differ")
    ports = data.get("NetworkSettings", {}).get("Ports", {}).get("5432/tcp", [])
    if len(ports) != 1 or ports[0].get("HostIp") != "127.0.0.1":
        raise ValueError("test database is not exclusively loopback bound")
    port = int(ports[0]["HostPort"])
    if not 1 <= port <= 65535:
        raise ValueError("invalid loopback port")
    return port


def cleanup(name, token, cid, attempted):
    if not attempted:
        return True
    observed = command(["docker", "inspect", cid or name, "--format", "{{json .}}"])
    if observed.returncode != 0:
        # An inspect error alone does not prove absence: the daemon may be down.
        listed = command(["docker", "container", "ls", "--all", "--filter", "name=^/" + name + "$", "--format", "{{.ID}}"])
        return listed.returncode == 0 and not listed.stdout.strip()
    try:
        actual = owned_container(inspected(observed), name, token, cid)
    except (ValueError, KeyError, TypeError):
        return False
    removed = command(["docker", "rm", "--force", "--volumes", actual])
    listed = command(["docker", "container", "ls", "--all", "--filter", "id=" + actual, "--format", "{{.ID}}"])
    return removed.returncode == 0 and listed.returncode == 0 and not listed.stdout.strip()


def application_accepted(path, database):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise ValueError("private database qualification receipt is required")
    data = json.loads(path.read_text())
    versions = data.get("migrationVersions", [])
    if (data.get("schemaVersion") != "execution-fabric-isolated-cold-qualification/v1"
            or data.get("databaseName") != database or data.get("accepted") is not True
            or data.get("epoch") != 7 or data.get("generation") != 3
            or data.get("providerOrObjectCalls") != 0
            or data.get("canaryHandler") != "fabric_cold_canary_v1" or data.get("canaryExecutor") != "execute_assignment"
            or data.get("canaryResultVerified") is not True
            or data.get("quarantine") != {"tasks": 1, "effects": 1, "alarms": 1, "artifacts": 1}
            or not any(str(version).startswith("016") for version in versions)
            or not re.fullmatch(r"[0-9a-f-]{36}", data.get("recoveryId", ""))
            or not re.fullmatch(r"[0-9a-f-]{36}", data.get("canaryTaskId", ""))):
        raise ValueError("actual isolated cold acceptance receipt differs")
    return data


def run_tests(root, output, url_file, password):
    env = {key: value for key, value in os.environ.items()
           if key not in {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "DATABASE_URL", "FABRIC_DATABASE_URL",
                          "FABRIC_TEST_DATABASE_URL", "FABRIC_INTEGRATION_TESTS", "NODE_OPTIONS"}}
    env.update(FABRIC_COLD_INTEGRATION_TESTS="1", FABRIC_COLD_TEST_DATABASE_URL_FILE=str(url_file),
               FABRIC_COLD_TEST_RECEIPT_FILE=str(output / "DATABASE-QUALIFICATION.json"))
    log_path = output / "qualification.log"
    fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w") as log:
            result = subprocess.run(["npm", "exec", "vitest", "--", "run", "tests/cold-recovery.test.ts"],
                                    cwd=root / CONTROL, env=env, stdout=log, stderr=subprocess.STDOUT,
                                    timeout=120, check=False)
        return result.returncode if result.returncode >= 0 else 3
    finally:
        # Logs stay private and must not retain generated fixture credentials.
        content = log_path.read_text(errors="replace")
        for secret in {password, quote(password, safe="")}:
            content = content.replace(secret, "[fixture credential removed]")
        log_path.write_text(content)


def qualify(root, output, token):
    name = "fabric-cold-test-" + token
    database = "fabric_cold_test_" + token
    env_file, url_file = output / "container-test.env", output / "database-url.private"
    receipt = {"schema_version": "execution-fabric-disposable-postgres-run/v1", "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
               "image": IMAGE, "owner_label": LABEL, "owner_token": token, "container_name": name,
               "database_name": database, "source_root": str(root), "provider_actions": 0,
               "host_database_volumes": 0, "container_started": False, "database_tests_executed": False,
               "teardown_verified": False, "scope": "isolated source qualification; no installed release, production fencing or backup/RPO claim"}
    cid, attempted, exit_code = None, False, 3
    try:
        present = command(["docker", "image", "inspect", IMAGE, "--format", "{{json .}}"])
        if present.returncode != 0:
            receipt.update(status="image_unavailable", reason="Accepted immutable image unavailable; pre-pull it in a separately authorized dependency step. No pull or fallback performed.")
        else:
            image = inspected(present)
            image_id = image.get("Id", "")
            if (not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id)
                    or not any(digest.split("@")[-1] == IMAGE.split("@")[-1] for digest in image.get("RepoDigests", []))):
                raise ValueError("accepted immutable image identity differs")
            receipt["image_id"] = image_id
            password = secrets.token_urlsafe(32)
            private_write(env_file, "POSTGRES_USER=cold_fixture\nPOSTGRES_PASSWORD=" + password + "\nPOSTGRES_DB=" + database + "\n")
            attempted = True
            created = command(["docker", "run", "--detach", "--name", name, "--label", LABEL + "=" + token,
                               "--memory", "512m", "--cpus", "1", "--restart", "no", "--publish", "127.0.0.1::5432",
                               "--env-file", str(env_file), IMAGE, "postgres", "-c", "fsync=on", "-c", "full_page_writes=on",
                               "-c", "synchronous_commit=on", "-c", "synchronous_standby_names=", "-c", "archive_mode=on",
                               "-c", "archive_command=test -d cold_archive || mkdir -p cold_archive; test -f cold_archive/%f || cp %p cold_archive/%f"])
            if created.returncode != 0:
                raise ValueError("disposable container create failed")
            cid = created.stdout.strip()
            if not re.fullmatch(r"[0-9a-f]{64}", cid):
                raise ValueError("invalid disposable container identity")
            receipt.update(container_started=True, container_id=cid)
            port = validate_container(inspected(command(["docker", "inspect", cid, "--format", "{{json .}}"])), name, token, cid, image_id)
            receipt["loopback_port"] = port
            deadline = time.monotonic() + 45
            while command(["docker", "exec", cid, "pg_isready", "-U", "cold_fixture", "-d", database], timeout=5).returncode != 0:
                if time.monotonic() >= deadline:
                    raise TimeoutError("isolated PostgreSQL readiness timeout")
                time.sleep(0.5)
            private_write(url_file, "postgresql://cold_fixture:" + quote(password, safe="") + "@127.0.0.1:" + str(port) + "/" + database + "\n")
            receipt["database_tests_executed"] = True
            exit_code = run_tests(root, output, url_file, password)
            receipt.update(test_exit_code=exit_code, test_log="qualification.log")
            if exit_code == 0:
                application_accepted(output / "DATABASE-QUALIFICATION.json", database)
                receipt.update(status="passed", application_receipt="DATABASE-QUALIFICATION.json", application_acceptance_verified=True)
            else:
                receipt.update(status="test_failed", application_acceptance_verified=False)
    except (OSError, ValueError, KeyError, TypeError, TimeoutError, subprocess.TimeoutExpired) as exc:
        receipt.update(status="fixture_failed", error_class=type(exc).__name__, application_acceptance_verified=False)
        exit_code = 3
    finally:
        receipt["teardown_verified"] = cleanup(name, token, cid, attempted)
        for file in (env_file, url_file):
            file.unlink(missing_ok=True)
        receipt["generated_test_credentials_removed"] = True
        if not receipt["teardown_verified"]:
            receipt.update(status="cleanup_unverified", teardown_refused="Exact ownership/absence could not be verified; no broad cleanup attempted.")
            exit_code = 4
        receipt.update(exit_code=exit_code, finished_at=dt.datetime.now(dt.timezone.utc).isoformat())
        document(output / "RUN-RECEIPT.json", receipt)
    return exit_code


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--output-parent", required=True)
    args = parser.parse_args(argv)
    try:
        root = source_root(args.source_root)
        parent = canonical_directory(args.output_parent)
        token = uuid4().hex
        output = parent / ("fabric-cold-recovery-" + token)
        output.mkdir(mode=0o700, exist_ok=False)
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "exit_code": 2, "error_class": type(exc).__name__, "reason": "Source/output admission refused before Docker; use owned canonical directories and provisioned builds."}))
        return 2
    exit_code = qualify(root, output, token)
    print(json.dumps({"ok": exit_code == 0, "exit_code": exit_code, "artifact_dir": str(output), "receipt": str(output / "RUN-RECEIPT.json")}))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
