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
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess
import time
from urllib.parse import quote
from uuid import UUID, uuid4

import jsonschema

IMAGE = "docker.io/library/postgres@sha256:742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193"
LABEL = "io.genomes.fabric.cold-qualification"
CONTROL = "services/execution-fabric-control-plane"
WITNESS = "services/execution-fabric-leadership-witness"
METADATA_FACTS = {
    "owner": "isolated-original-owner", "operator": "isolated-named-operator", "originalWorkItemId": "cold-original-work",
    "originalAssociationProof": "ORIGINAL-ASSOCIATION.json", "originalContextReceipt": "ORIGINAL-CONTEXT.json",
    "nonempty016UpgradePreserved": True, "sqliteWriteFenceThroughPgCommit": True, "expiredExactReplayVerified": True,
    "expiryRefusedFreshInspection": True, "canonicalHistoryPredatesFirstHold": True, "missingOrPostHoldHistoryRefused": True,
    "missingOrPostHoldReferenceRefused": True, "wrongOwnerOrApprovalRefused": True, "changedContextOrPolicyRefused": True,
    "changedDependencyOrEventRefused": True, "sameKeyConflictRefused": True, "stalePredecessorRefused": True,
    "dependencyHashPreserved": True, "quarantineHistoryHashPreserved": True, "completedAtPreserved": True,
    "foreignSiblingUnchanged": True, "claimDeliveryAdminReplayArtifactGuardsVerified": True, "laterGenerationInvalidatesReplay": True,
    "sameGenerationColdLedgerReplayVerified": True, "laterGenerationColdLedgerReplayRefused": True, "coldLedgerReplayPreservesHolds": True,
    "authorityPrivacyDriftRefused": True, "authorityPrivacyRollbackVerified": True, "authorityPrivacyPreservesRows": True,
    "providerOrObjectCalls": 0, "genericRequeueQualified": False, "providerOutcomeQualified": False, "productionIngressQualified": False,
    "retainedQuarantine": {"tasks": 2, "effects": 1, "alarms": 1, "artifacts": 1},
    "scope": "native disposable producer/original-association and held metadata seams; restored dependencies and legacy016 rows are storage fixtures",
}
CANONICAL_PRODUCERS = ["PolicyManager.normalizeAdmission", "PostgresLedger.admitTask", "state.db.connect", "state.work_items.upsert",
    "state.control_plane_facts.record_artifact_reference", "development_delivery.resolve_development_policies",
    "state.control_plane_facts.request_approval", "state.control_plane_facts.decide_approval"]


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


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _exact(value, expected):
    if type(value) is not type(expected):
        return False
    if isinstance(expected, dict):
        return value.keys() == expected.keys() and all(_exact(value[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        return len(value) == len(expected) and all(_exact(a, b) for a, b in zip(value, expected))
    return value == expected


def _uuid(value):
    try:
        return isinstance(value, str) and str(UUID(value)) == value
    except ValueError:
        return False


def observe_execution_policies(source, candidate):
    """Observe copied evidence with the source-bound native PolicyManager.

    Its fingerprint uses JS localeCompare ordering, not the cold JSON digest.
    The report is qualification evidence and never supplied as actor authority.
    """
    selected = shutil.which("node")
    if not selected:
        raise ValueError("qualified Node evidence runtime unavailable")
    node = Path(selected).resolve(strict=True)
    module = Path(__file__).resolve().parents[2] / CONTROL / "dist/src/policy.js"
    for file in (node, module):
        info = file.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid not in {0, os.geteuid()} or info.st_mode & 0o022:
            raise ValueError("qualified Node or source-bound PolicyManager unavailable")
    program = """import {pathToFileURL} from 'node:url';
const [module,source,candidate]=process.argv.slice(1);
const version=process.versions.node.split('.').map(Number);
if(version[0]!==22 || version[1]<17)throw new Error('unqualified Node engine');
const {PolicyManager}=await import(pathToFileURL(module).href);
const result=[source,candidate].map(file=>{const manager=new PolicyManager(file,'canonical-policy-schema-in-source');
manager.assertOperational();return {effectivePolicy:manager.effective(),appliedFingerprint:manager.snapshot().appliedFingerprint,state:manager.snapshot().state};});
const out=JSON.stringify(result);if(Buffer.byteLength(out)>4194304)throw new Error('bounded policy observation exceeded');process.stdout.write(out);
"""
    result = subprocess.run([str(node), "--input-type=module", "--eval", program, str(module), str(source), str(candidate)],
        capture_output=True, timeout=15, check=False, env={k: v for k, v in os.environ.items() if k not in {
            "NODE_OPTIONS", "NODE_PATH", "NODE_V8_COVERAGE", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "FABRIC_RUNTIME_ENV_FILE",
            "FABRIC_DATABASE_URL", "DATABASE_URL", "FABRIC_TEST_DATABASE_URL", "FABRIC_COLD_TEST_DATABASE_URL_FILE",
            "FABRIC_INTEGRATION_TESTS", "FABRIC_COLD_INTEGRATION_TESTS"}})
    if result.returncode or len(result.stdout) > 4_194_304:
        raise ValueError("actual source-bound PolicyManager observation refused")
    observed = json.loads(result.stdout)
    if not isinstance(observed, list) or len(observed) != 2:
        raise ValueError("actual source-bound PolicyManager observation differs")
    return observed


def metadata_disposition_accepted(directory, data):
    """Validate the real fixture's typed readbacks; never native authority input."""
    meta = data.get("metadataDisposition")
    dynamic = {"originalTaskId", "foreignSiblingTaskId", "originalAssociationProofSha256", "originalContextReceiptSha256", "contextSha256",
        "inspection", "inspectionSha256", "cancellation", "cancellationSha256", "cancellationEventSha256",
        "reaffirmedCancellation", "reaffirmedCancellationSha256", "reaffirmationEventSha256", "effectHold", "effectHoldSha256",
        "effectHoldEventSha256", "taskDecisionHistory", "effectDecisionHistory", "legacy016RowsSha256",
        "coldLedgerAcceptedReceipt", "coldLedgerAcceptedReceiptSha256", "unchangedColdRecoveryJournalSha256", "unchangedAcceptedAnchorSha256",
        "sourceExecutionPolicy", "sourceExecutionPolicySha256", "candidateExecutionPolicy", "candidateExecutionPolicySha256", "policyTransitionProof", "policyTransitionProofSha256"}
    if not isinstance(meta, dict) or set(meta) != set(METADATA_FACTS) | dynamic | {"schemaVersion", "canonicalProducers"}:
        raise ValueError("closed actual metadata disposition qualification required")
    if meta["schemaVersion"] != "execution-fabric-isolated-metadata-disposition-qualification/v1" or meta["canonicalProducers"] != CANONICAL_PRODUCERS or any(not _exact(meta[k], v) for k, v in METADATA_FACTS.items()):
        raise ValueError("actual metadata disposition qualification differs")
    if not _uuid(meta["originalTaskId"]) or not _uuid(meta["foreignSiblingTaskId"]) or meta["originalTaskId"] == meta["foreignSiblingTaskId"]:
        raise ValueError("genuine native task or independent sibling identity missing")
    for key in dynamic:
        if key.endswith("Sha256") and (not isinstance(meta[key], str) or not re.fullmatch(r"[a-f0-9]{64}", meta[key])):
            raise ValueError("qualification digest differs")
    def proof_bytes(name, hash_key):
        file = directory / name
        info = file.lstat()
        if file.resolve(strict=True) != file or not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077 or info.st_size > 4_194_304:
            raise ValueError("private original qualification proof bytes unavailable")
        content = file.read_bytes()
        if hashlib.sha256(content).hexdigest() != meta[hash_key]:
            raise ValueError("private original qualification proof bytes unavailable")
        return content
    for file_key, hash_key in [("originalAssociationProof", "originalAssociationProofSha256"), ("originalContextReceipt", "originalContextReceiptSha256")]:
        proof_bytes(meta[file_key], hash_key)
    schema = json.loads((Path(__file__).resolve().parents[2] / "schemas/execution-fabric-cold-disposition.schema.json").read_text())
    inspection = meta["inspection"]
    jsonschema.validate(inspection, {**schema, "$ref": "#/$defs/inspectionReceipt"}, format_checker=jsonschema.FormatChecker())
    if (meta["inspectionSha256"] != _digest(inspection) or inspection["recoveryId"] != data["recoveryId"]
            or inspection["generation"] != 3 or inspection["fabricEpoch"] != 7 or inspection["itemKind"] != "task"
            or inspection["itemId"] != meta["originalTaskId"] or inspection["workItemId"] != meta["originalWorkItemId"]
            or inspection["contextSha256"] != meta["contextSha256"] or inspection["owner"] != meta["owner"]
            or inspection["operator"] != meta["operator"] or inspection["routeQualified"] is not False
            or inspection["ownerBlocked"] is not False or inspection["decisionHistory"] != [] or inspection["priorDispositionSha256"] is not None
            or not _exact(inspection["dependencyCounts"], {k: 1 for k in ["attempts", "runs", "effects", "artifacts", "alarms"]})):
        raise ValueError("actual initial native inspection readback differs")
    accepted = meta["coldLedgerAcceptedReceipt"]
    expected_accept = {"schemaVersion": "execution-fabric-cold-ledger-receipt/v1", "operation": "accept", "recoveryId": data["recoveryId"],
        "planSha256": inspection["planSha256"], "fabricEpoch": 7, "generation": 3, "held": False, "residualQuarantine": True}
    if not _exact(accepted, expected_accept) or meta["coldLedgerAcceptedReceiptSha256"] != _digest(accepted) or inspection["acceptedReceiptSha256"] != meta["coldLedgerAcceptedReceiptSha256"]:
        raise ValueError("actual native cold acceptance identity or digest differs")
    anchor = json.loads(proof_bytes("ACCEPTED-ANCHOR.json", "unchangedAcceptedAnchorSha256"))
    anchor_keys = {"schemaVersion", "clusterId", "leader", "generation", "highestEpoch", "publicKeySha256", "lastReceiptSha256", "pending"}
    if not isinstance(anchor, dict) or set(anchor) != anchor_keys or not isinstance(anchor.get("publicKeySha256"), str) or not re.fullmatch(r"[a-f0-9]{64}", anchor["publicKeySha256"]) or not _exact(anchor, {
        "schemaVersion": "execution-fabric-recovery-anchor/v1", "clusterId": inspection["clusterId"], "leader": inspection["targetHost"],
        "generation": 3, "highestEpoch": 7, "publicKeySha256": anchor["publicKeySha256"], "lastReceiptSha256": _digest(accepted), "pending": None}):
        raise ValueError("actual unchanged accepted anchor binding differs")
    journal = json.loads(proof_bytes("ACCEPTED-COLD-JOURNAL.json", "unchangedColdRecoveryJournalSha256"))
    if not isinstance(journal, dict) or set(journal) != {"ok", "schemaVersion", "recoveryId", "planSha256", "phase", "receipts"} or not _exact(
        {k: v for k, v in journal.items() if k != "receipts"}, {"ok": True, "schemaVersion": "execution-fabric-cold-journal/v1", "recoveryId": data["recoveryId"], "planSha256": inspection["planSha256"], "phase": "ACCEPTED"}):
        raise ValueError("actual unchanged accepted journal binding differs")
    phases = ["APPROVED", "RESERVED", "LEDGER_HELD", "WITNESS_COMMITTED_HELD", "LEDGER_COMMITTED_HELD", "ANCHOR_COMMITTED", "CANARY_ADMITTED", "ACCEPTED"]
    references = journal["receipts"]
    if not isinstance(references, list) or len(references) != len(phases):
        raise ValueError("actual unchanged accepted journal phase history differs")
    for item, phase in zip(references, phases):
        if not isinstance(item, dict) or set(item) != {"phase", "ref", "sha256"} or item["phase"] != phase or not isinstance(item["ref"], str) or not Path(item["ref"]).is_absolute() or not isinstance(item["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", item["sha256"]):
            raise ValueError("actual unchanged accepted journal receipt reference differs")
    if references[-1]["sha256"] != _digest(accepted):
        raise ValueError("actual journal has another immutable acceptance receipt")
    names = {"sourceExecutionPolicy": "SOURCE-EXECUTION-POLICY.yml", "candidateExecutionPolicy": "CANDIDATE-EXECUTION-POLICY.yml", "policyTransitionProof": "POLICY-TRANSITION-PROOF.json"}
    for key, name in names.items():
        if meta[key] != name:
            raise ValueError("closed policy transition sidecar differs")
        proof_bytes(name, key + "Sha256")
    transition = json.loads(proof_bytes(meta["policyTransitionProof"], "policyTransitionProofSha256"))
    transition_keys = {"schemaVersion", "plan", "source", "candidate", "postgresBeforeHold", "postgresAfterHold", "postgresAfterCommit", "witnessSource", "witnessTarget",
        "originalTaskConfigFingerprint", "foreignSiblingConfigFingerprint", "acceptedPolicyFingerprint", "scope"}
    if not isinstance(transition, dict) or set(transition) != transition_keys or transition["schemaVersion"] != "execution-fabric-isolated-policy-transition-proof/v1" or transition["scope"] != "native disposable supported A initial activation and signed A-to-B cold transition; not a live or installed host transition":
        raise ValueError("closed actual policy transition proof differs")
    recovery_schema = json.loads((Path(__file__).resolve().parents[2] / "schemas/execution-fabric-cold-recovery.schema.json").read_text())
    plan = transition["plan"]
    jsonschema.validate(plan, {**recovery_schema, "$ref": "#/$defs/plan"}, format_checker=jsonschema.FormatChecker())
    if _digest(plan) != accepted["planSha256"] or plan["recoveryId"] != data["recoveryId"] or plan["nextEpoch"] != 7 or plan["generation"] != 3 or plan["clusterId"] != inspection["clusterId"] or plan["targetHost"] != inspection["targetHost"] or plan["newPgSystemId"] != inspection["pgSystemId"] or plan["policySha256"] != inspection["acceptedPolicySha256"] or anchor["publicKeySha256"] != plan["newPublicKeySha256"] or "policyTransition" not in plan:
        raise ValueError("signed actual policy transition plan differs")
    observations = observe_execution_policies(directory / names["sourceExecutionPolicy"], directory / names["candidateExecutionPolicy"])
    fingerprints = []
    for key, observation, enabled in zip(("source", "candidate"), observations, (False, True)):
        selected = transition[key]
        if not isinstance(selected, dict) or set(selected) != {"file", "rawSha256", "appliedFingerprint", "effectivePolicy", "state", "canaryEnabled"} or selected["file"] != names[key + "ExecutionPolicy"] or selected["rawSha256"] != meta[key + "ExecutionPolicySha256"] or not _exact({k: selected[k] for k in ("effectivePolicy", "appliedFingerprint", "state")}, observation) or selected["state"] != "applied" or selected["canaryEnabled"] is not enabled:
            raise ValueError("actual loaded execution policy observation differs")
        fingerprint = selected["appliedFingerprint"]
        if not isinstance(fingerprint, str) or not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
            raise ValueError("actual applied execution policy fingerprint differs")
        fabric = selected["effectivePolicy"]["execution_fabric"]
        queue = [item for item in fabric["queues"] if item["id"] == "fabric_cold_recovery"]
        pool = [item for item in fabric["worker_pools"] if item["id"] == "fabric_cold_recovery_workers"]
        if len(queue) != 1 or len(pool) != 1 or queue[0]["enabled"] is not enabled or pool[0]["enabled"] is not enabled:
            raise ValueError("actual source/target inert canary policy differs")
        fingerprints.append(fingerprint)
    source, candidate = fingerprints
    if source == candidate or plan["policyTransition"]["expectedSourceFingerprint"] != source or plan["candidateConfigDigest"] != candidate or plan["policyTransition"]["candidateExecutionPolicySha256"] != meta["candidateExecutionPolicySha256"] or inspection["configFingerprint"] != candidate:
        raise ValueError("actual signed source-to-candidate execution policy differs")
    for key, epoch, leader, fingerprint, recovery_id, generation, phase in [
            ("postgresBeforeHold", plan["expectedEpoch"], plan["sourceHost"], source, None, 0, None),
            ("postgresAfterHold", plan["expectedEpoch"], plan["sourceHost"], source, data["recoveryId"], 3, "LEDGER_HELD"),
            ("postgresAfterCommit", 7, plan["targetHost"], candidate, data["recoveryId"], 3, "LEDGER_COMMITTED_HELD")]:
        if not _exact(transition[key], {"current_epoch": epoch, "leader_host_id": leader, "policy_fingerprint": fingerprint,
                "cold_recovery_id": recovery_id, "cold_recovery_generation": generation, "cold_recovery_phase": phase}):
            raise ValueError("actual atomic PostgreSQL policy transition differs")
    source_witness, target_witness = transition["witnessSource"], transition["witnessTarget"]
    if not isinstance(source_witness, dict) or set(source_witness) != {"state", "version"} or not _exact(source_witness["state"], {"currentLeader": plan["sourceHost"], "fabricEpoch": plan["expectedEpoch"], "configDigest": source, "upstreamSystemId": None}) or type(source_witness["version"]) is not int or source_witness["version"] != plan["snapshotVersion"]:
        raise ValueError("actual source witness policy transition differs")
    if not isinstance(target_witness, dict) or set(target_witness) != {"state", "version", "receipt"} or not _exact(target_witness["state"], {"currentLeader": plan["targetHost"], "fabricEpoch": 7, "configDigest": candidate, "upstreamSystemId": plan["newPgSystemId"]}) or type(target_witness["version"]) is not int or target_witness["version"] <= source_witness["version"]:
        raise ValueError("actual target witness policy transition differs")
    witness_receipt = target_witness["receipt"]
    witness_keys = {"schemaVersion", "recoveryId", "planSha256", "previousLeader", "currentLeader", "fabricEpoch", "generation", "originalDatabasePath", "targetDatabasePath", "newPublicKeySha256", "committedAt", "held"}
    if not isinstance(witness_receipt, dict) or set(witness_receipt) != witness_keys or not isinstance(witness_receipt["committedAt"], str) or not _exact(witness_receipt, {"schemaVersion": "execution-fabric-cold-witness-receipt/v1", "recoveryId": data["recoveryId"], "planSha256": _digest(plan), "previousLeader": plan["sourceHost"], "currentLeader": plan["targetHost"], "fabricEpoch": 7, "generation": 3, "originalDatabasePath": plan["originalDatabasePath"], "targetDatabasePath": plan["targetDatabasePath"], "newPublicKeySha256": plan["newPublicKeySha256"], "committedAt": witness_receipt["committedAt"], "held": True}):
        raise ValueError("actual target witness retained receipt differs")
    if transition["originalTaskConfigFingerprint"] != source or transition["foreignSiblingConfigFingerprint"] != source or transition["acceptedPolicyFingerprint"] != candidate:
        raise ValueError("original and current execution policy bindings differ")
    association = json.loads(proof_bytes(meta["originalAssociationProof"], "originalAssociationProofSha256"))
    if association.get("task", {}).get("id") != meta["originalTaskId"] or association.get("task", {}).get("config_fingerprint") != source:
        raise ValueError("genuine original producer source policy binding differs")
    previous = None
    for name, event_key, kind, verb in [("cancellation", "cancellationEventSha256", "task", "task_cancel"),
            ("reaffirmedCancellation", "reaffirmationEventSha256", "task", "task_cancel"), ("effectHold", "effectHoldEventSha256", "effect", "hold")]:
        receipt = meta[name]
        jsonschema.validate(receipt, {**schema, "$ref": "#/$defs/receipt"}, format_checker=jsonschema.FormatChecker())
        if meta[name + "Sha256"] != _digest(receipt) or meta[event_key] != meta[name + "Sha256"]:
            raise ValueError("native receipt or actual committed event digest differs")
        for key in ["recoveryId", "generation", "fabricEpoch", "clusterId", "targetHost", "pgSystemId", "planSha256", "configFingerprint",
                    "acceptedReceiptSha256", "executionPolicySha256", "owner", "operator", "contextSha256", "workItemSha256", "policySha256", "dependencySha256"]:
            if not _exact(receipt[key], inspection[key]):
                raise ValueError("native decision accepted identity differs")
        if receipt["itemKind"] != kind or receipt["disposition"] != verb or (kind == "task" and receipt["itemId"] != meta["originalTaskId"]):
            raise ValueError("native exact item disposition differs")
        if receipt["predecessorSha256"] != (meta["cancellationSha256"] if name == "reaffirmedCancellation" else None):
            raise ValueError("native decision predecessor differs")
        if kind == "task" and receipt["beforeSha256"] != (previous["afterSha256"] if previous else inspection["itemSha256"]):
            raise ValueError("native task decision before-image differs")
        if kind == "task": previous = receipt
    expected = []
    for sequence, name in [(1, "cancellation"), (2, "reaffirmedCancellation"), (3, "effectHold")]:
        receipt = meta[name]
        expected.append({"sequence": sequence, "recoveryId": receipt["recoveryId"], "generation": 3, "fabricEpoch": 7,
                         "disposition": receipt["disposition"], "receiptSha256": meta[name + "Sha256"],
                         "predecessorSha256": receipt["predecessorSha256"], "eventId": receipt["eventId"]})
    if not _exact(meta["taskDecisionHistory"], expected[:2]) or not _exact(meta["effectDecisionHistory"], expected[2:]):
        raise ValueError("actual immutable per-item decision history differs")
    return meta


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
            or not _exact(data.get("quarantine"), {"tasks": 2, "effects": 1, "alarms": 1, "artifacts": 1})
            or not any(str(version).startswith("016") for version in versions)
            or not any(str(version).startswith("017") for version in versions)
            or not re.fullmatch(r"[0-9a-f-]{36}", data.get("recoveryId", ""))
            or not re.fullmatch(r"[0-9a-f-]{36}", data.get("canaryTaskId", ""))):
        raise ValueError("actual isolated cold acceptance receipt differs")
    metadata_disposition_accepted(path.parent, data)
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
            result = subprocess.run(["npm", "exec", "vitest", "--", "run", "--coverage.enabled", "--coverage.provider=v8",
                                     "--coverage.reporter=json", "--coverage.reporter=json-summary",
                                     "--coverage.reportsDirectory=" + str(output / "typescript-coverage"),
                                     "--coverage.include=src/**"],
                                    cwd=root / CONTROL, env=env, stdout=log, stderr=subprocess.STDOUT,
                                    timeout=240, check=False)
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
