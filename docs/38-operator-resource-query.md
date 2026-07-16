# 38 · Program and Automation Operator Resource Query

## Why this boundary exists

Command Center needs one dependable read path for Programs and Automations. The
filesystem currently contains definitions, installed instances, schedules,
configuration, run receipts, and logs in several canonical files. Joining those
sources inside every desktop screen would duplicate rules and hide drift.

`operator-resource-query/v1` is the read-only boundary. It uses one envelope,
diagnostic vocabulary, configuration-provenance model, and pair of CLI actions.
Program and Automation enrichers keep their own identity and evidence rules.

## Commands

```bash
agentic-os operator-resource query program --root ~/agentic_os
agentic-os operator-resource get program program_instance:los:team_pr_sync --root ~/agentic_os

agentic-os operator-resource query automation --root ~/agentic_os
agentic-os operator-resource get automation \
  automation_definition:los:engineering:active_prs_board --root ~/agentic_os
```

The commands always emit JSON. `get` accepts only an exact ID returned by
`query`; it does not resolve names or aliases.

## Shared envelope

| Field | Meaning |
| --- | --- |
| `api_version` | Fixed at `operator-resource-query/v1`. |
| `generated_at` | UTC projection time. |
| `query` | Resource kind and optional exact ID. |
| `resources` | Complete or partial source-backed projections. |
| `diagnostics` | Structured source, identity, dependency, and parsing findings. |
| `summary` | Counts, partial-result state, and `remote_probes: 0`. |

Every resource includes its exact identity, resource type, icon provenance,
effective configuration and field provenance, a host/harness/model/complexity
routing projection with per-field provenance, evidence-backed health, recent
local receipts, and resource-local diagnostics.

## Program rules

- Shared definitions live under `harness/shared_factory/00-programs/`.
- Installed instances live under each domain's `00-programs/` collection.
- An instance joins a definition only when its explicit `definition_id` exactly
  matches the definition ID. A matching folder or display name is never enough.
- Legacy instances without an overlay retain an explicit, deterministic legacy
  identity and produce an unmatched-definition diagnostic when no definition
  exists.
- Components remain visible even when a path dependency is missing.
- Configuration precedence is definition → config documents → instance overlay.
  Runtime stays `unknown` unless a durable runtime observation exists.
- A program icon comes from metadata when available; otherwise a stable hash of
  its ID selects a deterministic fallback.

## Automation rules

- The automation folder is the definition; its installed filesystem presence is
  represented by a separate instance identity.
- Schedule identity comes from explicit `automation_id`, `definition_id`, or
  `automation_ref`, or from an exact canonical automation folder path in a
  schedule command. Similar names are not treated as evidence.
- Queue runs join through exact schedule IDs.
- Last run, next run, and health use only joined schedule and queue receipts.
  `healthy`, `active`, `stale`, `error`, `disabled`, and `unknown` never imply a
  remote-host or process probe.
- Tracking-only runtime entries remain visible with missing-definition and
  placement diagnostics.
- Qualification findings come from the existing automation checker. Placement
  findings apply the existing OS authoring and harness-adapter requirements.

## Partial and malformed sources

The boundary is failure-tolerant. A malformed optional file, missing dependency,
unmatched instance, or tracking-only automation becomes a structured diagnostic.
Other readable resources remain available and `summary.partial` is true. The
boundary never repairs, writes, schedules, probes, or executes work.

## Ownership, routing, and validation

- Owner: Agentic OS source package.
- Runtime context: installed Agentic OS root supplied through `--root`.
- Desktop projection: Command Center reads the CLI output; it does not persist a
  competing Program or Automation registry.
- Schema: `schemas/operator-resource-query-v1.schema.json`.
- Tests: `tests/test_operator_resources.py` covers exact joins, unmatched and
  malformed sources, provenance precedence, icon selection, missing
  dependencies, stale/error health, placement denial, and fixed CLI readback.
