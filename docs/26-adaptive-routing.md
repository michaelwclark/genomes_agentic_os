# 26 · Adaptive Routing Operator Guide

> **Status:** planning and evaluation are offline contracts. The observation
> report aggregates existing redacted evidence into a canonical filesystem
> artifact and can append a projection to verified Genome's Notion; it still
> does not execute work, call model providers, create sub-agents, poll CI, or
> change harness configuration. Treat routing output as evidence, not proof that
> work ran.

Adaptive routing selects a capability-safe model tier, reasoning effort, and a
bounded execution topology from a task assessment and an explicit policy. It is
designed to preserve the existing static configuration when disabled, to expose
why a route was chosen, and to retain only redacted operational evidence.

## Architecture and trust boundaries

The controller has four separate responsibilities:

1. `task_assessment` derives a small, deterministic set of risk and scope
   signals from task text. The task text is not returned in a plan.
2. `adaptive_policy` loads and validates the versioned YAML policy, capability
   catalog, layer precedence, and safety floors.
3. `adaptive_router` resolves an `ExecutionPlan`; `adaptive_topology` turns a
   ready plan into bounded role contracts and waves. Neither component starts
   an agent or a tool.
4. `adaptive_receipts` accepts only the authoritative plan and topology,
   validates a privacy-safe projection, and produces a canonical receipt.
   `adaptive_evaluation` evaluates independently reviewed, redacted holdouts
   against a static baseline.

The owner is selected **before** model resolution. A matching workflow or skill
can raise the plan's requirements (tools, verification, approval, tier, or
reasoning floor), but cannot reduce assessment or policy requirements. The
parent verifier is the only integration authority for a multi-role topology.

Plans are intentionally non-authorizing. A selected tool is a requirement for a
later executor, not permission to use it. A human gate, unavailable capability,
or failed verification remains a structured outcome; the router must not retry
by silently choosing a weaker route.

## Configuration ownership

Keep the three configuration surfaces distinct.

| Surface | Owns | Do not put here |
| --- | --- | --- |
| Harness `config.toml` | Harness profile, MCP/tool scope, sandbox, and static model/reasoning defaults at each config layer. | Adaptive routing thresholds, customer exception logic, raw task data, or receipts. |
| Adaptive policy YAML | Mode, policy/versioned catalog, tier routes, capability/customer-safety constraints, and host → project → workflow → customer policy layers. | Secrets, provider credentials, customer content, or executable workflow instructions. |
| Skills and workflows | Owner identity, task procedure, required tools, validations, approvals, and the actual human/executor runbook. | A second model catalog or a weaker replacement for policy safety floors. |

Start from [`templates/runtime/adaptive-router.yml`](https://github.com/michaelwclark/genomes_agentic_os/blob/main/templates/runtime/adaptive-router.yml).
Its policy precedence is `host < project < workflow < customer < request`.
The request layer is per-run intent only: it can strengthen a route only if the
effective policy allows the requested model, and it can never lower a derived
assessment floor, a policy default floor, or a human approval gate.

For harness configuration mechanics, see [13 · Agent Surfaces](13-agent-surfaces.md)
and [23 · Configuration Surfaces](23-configuration-surfaces.md). The adaptive
policy is not a replacement for either of those contracts.

## Models, tiers, and reasoning

The supplied catalog assigns these stable roles:

| Model | Tier | Cost class | Default route reasoning |
| --- | --- | --- | --- |
| `gpt-5.6-luna` | economy | economy | medium |
| `gpt-5.6-terra` | balanced | standard | medium |
| `gpt-5.6-sol` | frontier | premium | high |

`frontier_max` and `human_gate` use the frontier model with `ultra` reasoning;
the latter also requires explicit human approval. Models advertise only their
supported reasoning levels. A policy cannot claim a lower capability tier for a
known model, and a route cannot select a model or effort that the catalog does
not support.

The plan budget is an upper bound used for planning, not an invoice or a
provider usage record. The receipt keeps provider usage as explicit unknowns
when a provider did not report it. In particular, a missing `cost_cents` is
**unknown**, not zero, free, estimated, or evidence that the route was cheaper.
Use independently reviewed `cost_assessment` evidence for `appropriate`,
`too_cheap`, or `too_expensive`; otherwise retain `unknown`.

## From plan to bounded topology

Simple work can remain `operator_only`. More involved work may use
worker/verifier, planner/implementer/verifier, or deep multi-lens contracts.
Topology depth is based on assessment, not the selected model alone: strengthening
a simple Jira plan to Sol does not manufacture sub-agents.

Every declared agent is bounded by the parent plan's model, reasoning, tools,
context budget, output budget, and dependencies. Contracts forbid self-expansion.
The topology module does not launch those contracts, so an executor must provide
the real dispatch integration and preserve the returned parent verifier contract.

Long waits use a watcher role only when the topology calls for one. Its contract
requires three relative artifacts—state, events, and summary—and explicitly
forbids chat polling. A watcher reports durable status; it does not decide that
CI, deployment, or approval succeeded.

## Lifecycle and rollout gate

| Mode | Meaning | Operator use |
| --- | --- | --- |
| `off` | Do not select an adaptive model. Return `static_fallback` and preserve Feature 62 static role-aware configuration. | Default safe rollback and opt-out state. |
| `observe` | Assess and report a route without treating a blocked/human-gated plan as executable authority. | Gather redacted plans and review outcomes. |
| `guarded` | Produce capability-safe ready plans and bounded topology contracts, with approvals and verification still required. | **First active mode.** |
| `enforce` | Make adaptive-policy selection mandatory for the integrated executor. | Disabled until an explicitly approved zero-breach holdout. |

Do not promote directly from `off` to `enforce`. First operate in `observe`,
then use `guarded` as the first active mode. Before enabling `enforce`, retain a
reviewed holdout evaluation with zero safety breaches, stable repeated runs, no
unresolved drift, and an explicit recorded approval for that holdout. An
evaluation `guarded_mode.decision: go` is evidence for guarded operation; it is
not by itself authorization to enforce.

Any project or customer can opt out by setting its effective policy mode to
`off`. That returns the Feature 62 static fallback rather than changing the
historical static profile. Do not delete prior receipts during an opt-out:
preserve their policy/version fingerprints and record the new opt-out in the
next receipt or change record.

### Last-known-good rollback

If a policy, catalog, evaluation, or integration change becomes suspect, stop
adaptive execution at the applicable layer by setting that layer to `off` and
return to the last known-good static profile. Feature 62's role-aware
`config.toml` layers remain the rollback authority for the static profile.
Preserve historical adaptive receipts exactly as created; rollback changes the
next route, not the record of prior decisions. Re-evaluate a corrected policy
against the approved holdout before another guarded promotion.

## Two redacted operator examples

### Simple Jira maintenance

Request (redacted): “Update Jira CC-216 status and add a triage label.”

Expected assessment: low scope, no production or data-risk signal. With a
guarded economy-default policy, the plan can select Luna at economy/medium and
produce an `operator_only` topology. The operator still follows the owning
workflow's tracker readback and approval rules; the plan itself does not update
the tracker.

An acceptable receipt projection uses opaque identifiers only:

```yaml
receipt_id: route-7d2e11a9c4b8
project_id: project-redacted
customer_id: null
routing:
  status: ready
  model_id: gpt-5.6-luna
  model_tier: economy
  reasoning_effort: medium
topology:
  kind: operator_only
verification:
  status: pending
provider_usage:
  cost_cents: null
  unknown_fields: [provider, input_tokens, output_tokens, cached_input_tokens, total_tokens, cost_cents, latency_ms]
```

This is a routing receipt, not a claim that a Jira update occurred. After the
external operation, attach only safe relative artifact references and an
observed outcome; do not paste issue text, names, URLs containing customer data,
or credentials into the receipt.

### Complex monolith change

Request (redacted): “Refactor the monolith across multiple modules and update its API.”

The conservative result can require frontier capability and select Sol at
frontier/high. It can produce a `deep_multi_lens` topology with researcher,
planner, implementer, watcher, and a parent integration verifier. The watcher
uses its durable state/events/summary artifacts; the verifier waits on declared
dependencies and accepts or rejects the integrated result. No role may add
another agent, broaden its tools, or bypass the required verification.

Redacted evidence should name contracts and artifacts, not source contents:

```yaml
receipt_id: route-3a59f0ce81d7
project_id: project-redacted
routing:
  status: ready
  model_id: gpt-5.6-sol
  model_tier: frontier
  reasoning_effort: high
topology:
  kind: deep_multi_lens
  execution_waves: [[planner], [researcher, implementer], [watcher], [verifier]]
escalation:
  events: []
verification:
  status: pending
```

If a test, capability, or verifier check fails, record the structured escalation
with safe evidence references. Do not report a passing outcome until the
integrated executor and verifier have actually produced it.

## Status and evaluation interpretation

Plan status answers what the controller decided, not what the world did:

| Status | Meaning | Operator action |
| --- | --- | --- |
| `ready` | A policy-safe route is available. | Send it only to an authorized executor; preserve required gates. |
| `static_fallback` | Adaptive routing is off. | Use Feature 62 static configuration. |
| `human_approval_required` | A route needs recorded human approval. | Obtain approval; do not downgrade the route. |
| `blocked` | No safe selectable route exists. | Fix policy/catalog/capability evidence or stop. |

Holdout reports intentionally omit task text and provider pricing. Read their
denominators, case IDs, fingerprints, drift fields, threshold breaches, quality
parity, false-cheap/false-expensive rates, and repeated-run stability together.
A zero numerator with zero eligible cases is not proof of safety. Any drift,
breach, unresolved review status, or instability blocks promotion. Evaluation
is offline and compares redacted reviewed bounds/outcomes with a static baseline;
it is not live telemetry or a deployment test.

## Observe reports

At the start of a substantive Codex task, the generated Agentic OS guidance
records one non-executing, text-free decision receipt using the active Codex
thread and current turn as the correlation boundary:

```bash
agentic-os adaptive-routing observe \
  --root <root> \
  "<original user request>"
```

The task text is assessed in memory and is not written to the ledger. The
reporter later finds the exact Codex turn containing the observation timestamp,
uses per-turn token events rather than session-lifetime counters, and attributes
child rollout usage to the parent turn. A missing or ambiguous turn remains
unknown rather than inheriting the last model or cumulative session usage.

`agentic-os adaptive-routing report` turns the last observation window into an
operator-readable report without making a promotion decision. The scheduled
window is 12 hours. A useful review answers these questions explicitly:

- How many eligible receipts were found, and how many were excluded or invalid?
- Which policy versions, modes, model tiers, reasoning levels, topology kinds,
  route statuses, projects, and workflows were represented?
- Did any capability, safety, approval, verification, quality, cost, latency,
  stability, or policy-drift signal breach its reviewed bound?
- Were routes assessed as too cheap, too expensive, or appropriate, and what is
  the denominator behind each rate?
- Which facts remain unknown because no authoritative provider or reviewer
  evidence exists?
- What changed from the previous comparable window, and is the comparison valid
  across the same policy, schema, catalog, and pricing versions?

A report with no eligible receipts is an explicit `insufficient_evidence`
observation, not a zero-breach success. Missing usage, reviewed outcomes,
latency, quality, or pricing stays `unknown`; it must never be filled with zero,
an inferred provider value, or a claim that the route was free. Report known and
unknown counts together so operators can see denominator quality.

### Canonical artifact and Notion projection

The filesystem is canonical. Reports live under
`harness/shared_factory/06-runs-and-logs/adaptive-routing/observation-reports/`
and must contain the complete redacted evidence, version identifiers, window,
unknowns, and projection status. Notion is a readable projection only. With
`--apply-notion`, the command may append to **verified Genome's Notion** after
workspace verification; it must not overwrite prior observations or write to a
fallback workspace. If verification or access fails, preserve the filesystem
report and record the projection as blocked with the exact reason.

Repeated execution for the same report identity must reuse the canonical result
and must not append a duplicate Notion projection. The runtime schedule also
uses one idempotency key per due window. Neither mechanism authorizes editing or
deleting an earlier report.

Pricing evidence is versioned input, not ambient knowledge. Every known price
must carry a pricing-catalog version (and effective date or source fingerprint)
that can be compared with the receipt's model and usage units. If the applicable
version is absent, incompatible, or does not cover the selected model, cost is
`unknown`. Do not silently reprice historical windows with a current catalog;
publish a separately identified recomputation if reviewed historical analysis
is required.

### Operator runbook

1. Confirm the effective adaptive policy mode and inspect the filesystem receipt
   window. In `off`, expect static-fallback observations; do not interpret them
   as adaptive selections.
2. Preview locally with
   `agentic-os adaptive-routing report --root <root> --hours 12`. Review the
   window, versions, denominators, exclusions, unknowns, and all breaches.
3. If a Notion projection is required, verify the destination is Genome's
   Notion, then run the scheduled contract exactly:
   `agentic-os adaptive-routing report --root <root> --hours 12 --apply-notion`.
4. Check the canonical report first, then confirm its projection status. A
   Notion failure does not invalidate a complete local report, but it is an
   operational blocker to projection and must remain visible.
5. Investigate breaches or drift before changing policy. Observation reports do
   not authorize `guarded` or `enforce`; use the reviewed lifecycle gate.

To stop automated reporting, set the
`adaptive_routing_observation_report` runtime schedule to `enabled: false`.
To stop adaptive selection, set the applicable adaptive policy layer to `off`.
These are separate controls. Keep canonical reports and append-only projections
in both cases. Roll back routing through the last-known-good policy/static
profile process; do not delete evidence, rewrite pricing versions, or use a
reporting disablement as a substitute for policy rollback.

## Failures, receipts, privacy, and customer delivery

Fail closed when the policy is invalid, a selected model is unavailable, a
reasoning effort is unsupported, a capability floor is unmet, a human gate is
missing, or receipt validation rejects data. Do not silently retry with a lower
tier. For an execution failure, use the topology's declared retry, replan, or
block escalation and attach only normalized relative artifact paths. A watcher
failure is an operational result to investigate; it is not permission to chat
poll or to infer a terminal external outcome.

Receipts accept opaque IDs, enumerated facts, allowlisted topology contract text,
and normalized relative artifact paths. They reject raw task text, absolute or
parent-traversal paths, secrets, encoded secret-like values, common personal or
customer-data patterns, and customer content. Default receipt retention is 30
days and aggregate retention is 90 days; customer content is always false. Set
customer retention and packaging requirements before delivery, export only the
redacted receipt/evaluation projections, and keep customer evidence in the
customer-approved system of record rather than routing telemetry.

For upgrades, pin and retain the policy, catalog, execution-plan, topology,
receipt, and evaluator schema versions plus report fingerprints. Validate the
new policy/template in `off` or `observe`, compare an approved holdout to its
static baseline, and promote only through the lifecycle above. Never rewrite
old receipts to match a new schema or model catalog.

## CLI and integration boundary

The registered command group is `agentic-os adaptive-routing`. Planning,
evaluation, status, and rollback commands are offline and non-executing. The
report command is also non-executing with respect to routed work, but it writes
the canonical report and, only with `--apply-notion`, can append its projection
to verified Genome's Notion. No command mutates policy files.

```bash
# Redacted dry-run plan. Task text is assessed locally and omitted from output.
agentic-os adaptive-routing plan \
  --policy-file templates/runtime/adaptive-router.yml \
  "Update Jira CC-216 status and add a label"

# A no-sub-agent request is accepted only when required verification survives.
agentic-os adaptive-routing plan \
  --policy-file templates/runtime/adaptive-router.yml \
  --no-sub-agents \
  "Update Jira CC-216 status"

# Run the reviewed holdout and record explicit guarded-mode approval.
agentic-os adaptive-routing evaluate \
  --holdout-file tests/fixtures/adaptive_routing_holdout.yml \
  --policy-file <candidate-enforce-policy.yml> \
  --approve

# Inspect lifecycle state; an approved holdout report is required for enforce.
agentic-os adaptive-routing status \
  --policy-file templates/runtime/adaptive-router.yml \
  --holdout-report <approved-holdout-report.json>

# Produce rollback instructions without applying them or deleting receipts.
agentic-os adaptive-routing rollback-plan \
  --policy-file templates/runtime/adaptive-router.yml \
  --last-known-good-policy-file <reviewed-policy.yml>

# Build a 12-hour canonical observation report and append its Notion projection.
agentic-os adaptive-routing report \
  --root <root> \
  --hours 12 \
  --apply-notion
```

`plan` supports strengthening tier, model, reasoning, owner, and verification
inputs; it never allows them to lower policy or assessment floors. The
`rollback-plan` output preserves historical receipt semantics and points to the
Feature 62 static fallback, but an operator must apply the reviewed change
through the normal configuration lifecycle. None of these commands is a
live-execution interface.

See also [18 · Troubleshooting & FAQ](18-troubleshooting-and-faq.md),
[08 · Runs & Run Logs](08-runs-and-run-logs.md), and
[14 · Config, Update & Backup](14-config-update-backup.md).
