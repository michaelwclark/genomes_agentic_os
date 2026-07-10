"""Deterministic, privacy-safe task assessment for adaptive routing.

This module deliberately has no dependency on ``adaptive_policy``.  It turns
task text into a small, immutable set of conservative routing signals; policy
code may interpret the stable tier strings later.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Final


SCHEMA_VERSION: Final = 1

# These are strings rather than policy enums so this module remains a leaf
# dependency.  Their order is used only while deriving a minimum tier.
TIER_ORDER: Final = {
    "economy": 0,
    "balanced": 1,
    "frontier": 2,
    "frontier_max": 3,
    "human_gate": 4,
}

_WORD = r"(?<![a-z0-9]){term}(?![a-z0-9])"

_RISK_PATTERNS: Final[dict[str, tuple[str, ...]]] = {
    "production": ("production", "prod", "live environment"),
    "destructive_action": (
        "delete",
        "destroy",
        "drop table",
        "truncate",
        "purge",
        "wipe",
    ),
    "auth_security": (
        "authentication",
        "authorization",
        "auth",
        "oauth",
        "credential",
        "secret",
        "security",
        "permission",
        "access control",
    ),
    "billing": ("billing", "invoice", "payment", "charge", "refund", "subscription"),
    "customer_data": (
        "customer data",
        "customer record",
        "customer billing data",
        "personal data",
        "pii",
        "ssn",
        "social security number",
    ),
    "migration": (
        "migration",
        "schema change",
        "database schema",
        "alembic",
        "django migration",
    ),
    "infrastructure": (
        "infrastructure",
        "terraform",
        "kubernetes",
        "k8s",
        "helm",
        "dns",
        "load balancer",
    ),
    "release": ("release", "deploy", "deployment", "rollout", "ship to"),
    "sensitive_external_write": (
        "send email",
        "send a message",
        "post to slack",
        "publish",
        "write to notion",
        "external write",
    ),
}

_INJECTION_PATTERNS: Final = (
    re.compile(
        r"\b(?:ignore|disregard|bypass|override|forget)\b"
        r"(?:\s+all)?\s+(?:prior|previous|system|developer|assistant|safety|security|rules?|instructions?)\b"
    ),
    re.compile(r"\b(?:disable|evade|circumvent)\b\s+(?:safeguards?|guardrails?|approval|human gate)\b"),
    re.compile(r"\bdo not\s+(?:assess|consider|apply)\s+(?:risk|safety|rules?)\b"),
    # Tool/shell imperatives embedded as instructions are adversarial routing
    # evidence.  The task text cannot turn an arbitrary command into authority.
    re.compile(
        r"\b(?:run|execute|invoke|call|use)\b\s+(?:the\s+)?"
        r"(?:shell|terminal|bash|zsh|powershell|command|tool|curl|wget|rm|chmod)\b"
    ),
)

# Structural policy weakening is intentionally broader than a phrase list.
# Authority vocabulary near downgrade, optionality, cheap-routing, or execution
# vocabulary is adversarial routing evidence even when wording is novel.
_AUTHORITY_TERMS: Final = frozenset(
    {
        "policy",
        "policies",
        "safeguard",
        "safeguards",
        "guardrail",
        "guardrails",
        "developer",
        "system",
        "authority",
        "instruction",
        "instructions",
        "rule",
        "rules",
        "safety",
        "security",
        "requirement",
        "requirements",
        "approval",
        "gate",
        "gates",
    }
)
_WEAKENING_OR_EXECUTION_TERMS: Final = frozenset(
    {
        "weaken",
        "weakens",
        "weakened",
        "weakening",
        "downgrade",
        "downgrades",
        "downgraded",
        "downgrading",
        "lower",
        "lowered",
        "lowering",
        "relax",
        "relaxed",
        "relaxing",
        "loosen",
        "loosened",
        "bypass",
        "ignore",
        "disregard",
        "override",
        "disable",
        "binding",
        "cheap",
        "cheaper",
        "cheapest",
        "cheaply",
        "economy",
        "optional",
        "advisory",
        "nonbinding",
        "execution",
        "execute",
        "executing",
        "routing",
        "route",
    }
)
_STRUCTURAL_INJECTION_WINDOW: Final = 16

_CODE_PATTERNS: Final = (
    "code",
    "implement",
    "fix",
    "bug",
    "test",
    "refactor",
    "function",
    "class",
    "module",
    "api",
    "repository",
    "python",
    "typescript",
    "javascript",
)
_CROSS_MODULE_PATTERNS: Final = (
    "cross-module",
    "cross module",
    "multiple modules",
    "monolith",
    "architecture",
    "across the codebase",
    "system-wide",
)
_JIRA_PATTERNS: Final = ("jira", "ticket", "issue", "backlog")
_JIRA_GRUNT_PATTERNS: Final = (
    "comment",
    "update",
    "status",
    "label",
    "assign",
    "triage",
    "link",
    "close",
    "prioritize",
)
_READ_ONLY_PATTERNS: Final = (
    "review",
    "inspect",
    "read",
    "summarize",
    "explain",
    "analyze",
    "diagnose",
    "investigate",
)


@dataclass(frozen=True, slots=True)
class TaskAssessment:
    """Versioned, immutable assessment with no retained task text."""

    schema_version: int
    task_family: str
    mutation_scope: str
    code_scope: str
    risk_flags: tuple[str, ...]
    uncertainty: str
    verification_needs: tuple[str, ...]
    context_depth: str
    expected_duration: str
    confidence: float
    minimum_tier: str
    human_gate: bool
    evidence: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        """Return serializable derived signals without task text or excerpts."""
        return {
            "schema_version": self.schema_version,
            "task_family": self.task_family,
            "mutation_scope": self.mutation_scope,
            "code_scope": self.code_scope,
            "risk_flags": list(self.risk_flags),
            "uncertainty": self.uncertainty,
            "verification_needs": list(self.verification_needs),
            "context_depth": self.context_depth,
            "expected_duration": self.expected_duration,
            "confidence": self.confidence,
            "minimum_tier": self.minimum_tier,
            "human_gate": self.human_gate,
            "evidence": list(self.evidence),
        }


def assess_task(task_text: str) -> TaskAssessment:
    """Assess a task using lexical rules that cannot be overridden by its text.

    ``task_text`` is purposefully used only during this call.  The returned
    object contains opaque signal labels, not the original task or matched
    snippets, so it is safe to serialize into routing logs.
    """
    text = _normalise(task_text)
    risks = _detect_risks(text)
    injection_detected = any(
        pattern.search(text) for pattern in _INJECTION_PATTERNS
    ) or _detect_structural_injection(text)
    family, code_scope, context_depth, duration, confidence = _classify(text)

    if risks:
        confidence = min(confidence, 0.85)
    if injection_detected:
        # An adversarial instruction is evidence of ambiguity, never a policy
        # instruction.  It cannot remove a lexical risk signal.
        confidence = min(confidence, 0.45)

    mutation_scope = _mutation_scope(text, risks, code_scope)
    verification = _verification_needs(family, risks, mutation_scope)
    minimum_tier = _minimum_tier(family, risks, confidence, injection_detected)
    human_gate = bool(
        {"production", "destructive_action", "sensitive_external_write"}.intersection(risks)
    )
    uncertainty = _uncertainty(confidence)
    evidence = _evidence(family, code_scope, risks, injection_detected)

    return TaskAssessment(
        schema_version=SCHEMA_VERSION,
        task_family=family,
        mutation_scope=mutation_scope,
        code_scope=code_scope,
        risk_flags=risks,
        uncertainty=uncertainty,
        verification_needs=verification,
        context_depth=context_depth,
        expected_duration=duration,
        confidence=confidence,
        minimum_tier=minimum_tier,
        human_gate=human_gate,
        evidence=evidence,
    )


def _normalise(task_text: str) -> str:
    if not isinstance(task_text, str):
        raise TypeError("task_text must be a string")
    return " ".join(task_text.casefold().split())


def _detect_structural_injection(text: str) -> bool:
    """Detect policy-authority weakening without retaining matched text."""

    tokens = re.findall(r"[a-z0-9]+", text)
    authority_positions = [
        index for index, token in enumerate(tokens) if token in _AUTHORITY_TERMS
    ]
    weakening_positions = [
        index
        for index, token in enumerate(tokens)
        if (
            token in _WEAKENING_OR_EXECUTION_TERMS
            or token.startswith(("waiv", "suspend", "suspens"))
        )
    ]
    proximity_match = any(
        abs(authority - weakening) <= _STRUCTURAL_INJECTION_WINDOW
        for authority in authority_positions
        for weakening in weakening_positions
    )
    non_binding_match = bool(
        re.search(r"\bnon[\s-]+binding\b", text)
        and authority_positions
    )
    does_not_apply_match = bool(
        re.search(
            r"\b(?:(?:does|do|is|are)\s+not\s+(?:apply|applicable)"
            r"|(?:doesn['’]t|isn['’]t|aren['’]t)\s+(?:apply|applicable)"
            r"|(?:cannot|can['’]t)\s+apply"
            r"|(?:is|are)\s+inapplicable"
            r"|no\s+longer\s+appl(?:y|ies|icable))\b",
            text,
        )
        and authority_positions
    )
    return proximity_match or non_binding_match or does_not_apply_match


def _contains(text: str, phrase: str) -> bool:
    return bool(re.search(_WORD.format(term=re.escape(phrase)), text))


def _detect_risks(text: str) -> tuple[str, ...]:
    return tuple(
        name
        for name, patterns in _RISK_PATTERNS.items()
        if any(_contains(text, pattern) for pattern in patterns)
    )


def _classify(text: str) -> tuple[str, str, str, str, float]:
    cross_module = any(_contains(text, pattern) for pattern in _CROSS_MODULE_PATTERNS)
    code_work = any(_contains(text, pattern) for pattern in _CODE_PATTERNS)
    jira_work = any(_contains(text, pattern) for pattern in _JIRA_PATTERNS)
    jira_grunt = any(_contains(text, pattern) for pattern in _JIRA_GRUNT_PATTERNS)

    if cross_module:
        return "cross_module_monolith", "cross_module", "deep", "long", 0.90
    if code_work:
        scope = "single_file" if re.search(r"\b[\w-]+\.(?:py|ts|tsx|js|jsx|go|rb|java)\b", text) else "bounded_module"
        return "bounded_code_change", scope, "standard", "medium", 0.85
    if jira_work and jira_grunt:
        return "simple_jira_grunt_work", "none", "shallow", "short", 0.95
    return "general_task", "none", "standard", "medium", 0.60


def _mutation_scope(text: str, risks: tuple[str, ...], code_scope: str) -> str:
    if "sensitive_external_write" in risks:
        return "sensitive_external_write"
    if code_scope != "none":
        return "code_change"
    if any(_contains(text, pattern) for pattern in _READ_ONLY_PATTERNS):
        return "read_only"
    if any(_contains(text, pattern) for pattern in _JIRA_GRUNT_PATTERNS):
        return "tracker_update"
    return "unspecified"


def _verification_needs(
    family: str, risks: tuple[str, ...], mutation_scope: str
) -> tuple[str, ...]:
    needs: set[str] = set()
    if family == "bounded_code_change":
        needs.add("targeted_tests")
    elif family == "cross_module_monolith":
        needs.update({"targeted_tests", "integration_tests", "change_review"})
    if mutation_scope == "tracker_update":
        needs.add("tracker_readback")
    if "migration" in risks:
        needs.update({"migration_plan", "rollback_plan"})
    if "infrastructure" in risks or "release" in risks:
        needs.update({"deployment_plan", "rollback_plan"})
    if "auth_security" in risks:
        needs.add("security_review")
    if "billing" in risks or "customer_data" in risks:
        needs.add("data_impact_review")
    if {"production", "destructive_action", "sensitive_external_write"}.intersection(risks):
        needs.add("human_approval")
    return tuple(sorted(needs))


def _minimum_tier(
    family: str, risks: tuple[str, ...], confidence: float, injection_detected: bool
) -> str:
    tier = "economy" if family == "simple_jira_grunt_work" else "balanced"
    if family == "cross_module_monolith":
        tier = "frontier"
    if risks:
        tier = _at_least(tier, "balanced")
    if {"auth_security", "billing", "customer_data", "migration", "infrastructure", "release"}.intersection(risks):
        tier = _at_least(tier, "frontier")
    if {"production", "destructive_action", "sensitive_external_write"}.intersection(risks):
        tier = _at_least(tier, "human_gate")
    if confidence < 0.70:
        tier = _at_least(tier, "balanced")
    if injection_detected:
        # An adversarial request is never sent to the cheapest route, even
        # when it does not happen to contain another lexical risk flag.
        tier = _at_least(tier, "frontier")
    return tier


def _at_least(current: str, candidate: str) -> str:
    return candidate if TIER_ORDER[candidate] > TIER_ORDER[current] else current


def _uncertainty(confidence: float) -> str:
    if confidence < 0.50:
        return "high"
    if confidence < 0.80:
        return "medium"
    return "low"


def _evidence(
    family: str, code_scope: str, risks: tuple[str, ...], injection_detected: bool
) -> tuple[str, ...]:
    signals = [f"family:{family}", f"code_scope:{code_scope}"]
    signals.extend(f"risk:{risk}" for risk in risks)
    if injection_detected:
        signals.append("adversarial_instruction_detected")
    return tuple(signals)
