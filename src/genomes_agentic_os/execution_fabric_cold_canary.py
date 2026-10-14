"""Fixed in-memory cold-recovery canary: no process, provider, file or network IO."""
from __future__ import annotations

from typing import Any, Mapping
from uuid import UUID

CANARY_TASK_TYPE = "fabric.cold_canary"
CANARY_QUEUE = "fabric_cold_recovery"
CANARY_NAMESPACE = "fabric_cold_recovery"
CANARY_POOL = "fabric_cold_recovery_workers"
CANARY_HANDLER = "fabric_cold_canary_v1"
CANARY_CAPABILITY = "fabric.cold_canary"
PAYLOAD_SCHEMA = "execution-fabric-cold-canary/v1"
RESULT_SCHEMA = "execution-fabric-cold-canary-result/v1"


def validate_canary_payload(value: Mapping[str, Any], **bindings: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"schema_version", "recovery_id", "cluster_id", "epoch", "generation"}:
        raise ValueError("cold canary requires its fixed closed payload")
    payload = dict(value)
    if payload["schema_version"] != PAYLOAD_SCHEMA:
        raise ValueError("cold canary payload schema differs")
    if not isinstance(payload["recovery_id"], str) or str(UUID(payload["recovery_id"])) != payload["recovery_id"]:
        raise ValueError("cold canary recovery identity differs")
    if not isinstance(payload["cluster_id"], str) or not payload["cluster_id"] or len(payload["cluster_id"]) > 128:
        raise ValueError("cold canary cluster identity differs")
    if any(type(payload[key]) is not int or not 1 <= payload[key] <= 9_007_199_254_740_991 for key in ("epoch", "generation")):
        raise ValueError("cold canary counters differ")
    if any(key not in payload or type(payload[key]) is not type(value) or payload[key] != value for key, value in bindings.items()):
        raise ValueError("cold canary differs from its signed recovery binding")
    return payload


def canary_result(payload: Mapping[str, Any], task_id: str) -> dict[str, Any]:
    validated = validate_canary_payload(payload)
    if str(UUID(task_id)) != task_id:
        raise ValueError("cold canary task identity differs")
    return {**validated, "schema_version": RESULT_SCHEMA, "handler": CANARY_HANDLER, "task_id": task_id}


def cold_canary_worker(_root: Any, assignment: Mapping[str, Any], task: Mapping[str, Any], route: Mapping[str, Any]) -> dict[str, Any]:
    """Return only the exact declared binding; never dispatch a supplied action."""
    if (task.get("taskType") != CANARY_TASK_TYPE or task.get("queue") != CANARY_QUEUE
            or task.get("namespace") != CANARY_NAMESPACE or route.get("domain_worker") != CANARY_HANDLER
            or route.get("command_template") is not None or route.get("allowed_effect_types") != []
            or task.get("requiredCapabilities") != [CANARY_CAPABILITY]):
        raise ValueError("cold canary task/route is not the fixed inert handler")
    payload = validate_canary_payload(task.get("payload"), epoch=assignment.get("fabricEpoch"))
    return {"result": canary_result(payload, task["id"]), "effects": [], "artifacts": []}
