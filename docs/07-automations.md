# 07 · Automations

> **Purpose:** An automation is a workflow that has been proven, documented, and
> promoted to run on a recurring trigger or event — without requiring a fresh
> human prompt each time. This page explains how to qualify a workflow as an
> automation, how the maturity ladder gates what the automation is allowed to do,
> and which CLI commands manage it.

> **You'll use this when:** a workflow runs often enough that manually invoking it
> each time adds friction, and you've collected enough evidence to describe its
> trigger, idempotency strategy, permissions, and failure recovery.

> **Prerequisites:** a domain, a lane, and at least one proven workflow in it.
> See [06 · Workflows](06-workflows.md) and
> [04 · Information Architecture](04-information-architecture.md).

---

## What an automation is

A workflow answers "how does this work?". An automation adds "when does it run,
what is it allowed to touch, and what happens if it fails?"

The upgrade is structural: the automation spec lives in the domain's
`04-automations/` directory under a lane, and it carries seven required files that
the CLI validates before allowing any maturity advancement.

```
<domain>/04-automations/<lane>/<automation>/
  automation.md       ← identity, trigger, idempotency, permissions, outputs, audit
  inputs.md           ← input table (what arrives and from where)
  outputs.md          ← output table (what is written and where)
  permissions.md      ← automation level, permission record, ask-before-acting rules
  failure-modes.md    ← failure table (what breaks and how the automation reacts)
  runbook.md          ← Start · Operate · Recover sections
  tests.md            ← Dry Run · Failure Tests sections
  logs/               ← run evidence folder (README.md required)
```

Names are `snake_case` — lowercase letters, digits, and underscores only. Hyphens
are rejected at creation time.

---

## The maturity ladder

Every automation starts at `observe` and can be advanced one step at a time. The
ladder is a safety posture: each level expands what the agent is allowed to do,
and `automation set-maturity` refuses to advance past the two safe-start levels
unless `automation check` reports zero blockers.

![Maturity ladder: observe and prepare are SAFE_START levels; advancing to propose, execute_approved, or execute_guarded requires passing the blocker gate — automation check with no blockers; an advance attempt with unresolved blockers is refused and the level stays unchanged](diagrams/automations-maturity-ladder.png)

| Level | Allowed behaviour |
| --- | --- |
| `observe` | Read systems and write summaries. No external writes. **SAFE_START.** |
| `prepare` | Draft work items, comments, replies, or plans. No approval required. **SAFE_START.** |
| `propose` | Recommend actions and request explicit approval before acting. |
| `execute_approved` | Execute actions after a human has explicitly approved each run. |
| `execute_guarded` | Execute within pre-approved limits, record evidence of every action. |

`SAFE_START_LEVELS = ("observe", "prepare")`. Advancing to `observe` or `prepare`
never requires a clean check — you can always fall back to a safe level. Advancing
to `propose`, `execute_approved`, or `execute_guarded` requires zero blockers from
`automation check`.

Nothing executes externally without the maturity level and approval rules
permitting it. At `observe` and `prepare`, external mutation is structurally
impossible by contract: the spec prohibits it and the agent must follow the spec.

---

## Required files and sections

`automation check` validates both the presence of files and the required sections
inside them. The full requirements (from `automation_ops.py`):

| File | Required sections / table headers |
| --- | --- |
| `automation.md` | `Metadata` · `Trigger` · `Idempotency` · `Permissions` · `Outputs` · `Audit Requirements` |
| `inputs.md` | Table with columns `Input | Required | Source | Validation` |
| `outputs.md` | Table with columns `Output | Destination | Required | Notes` |
| `permissions.md` | `Automation Level` · `Permission Record` · `Ask-Before-Acting Rules` |
| `failure-modes.md` | `Failure Table` |
| `runbook.md` | `Start` · `Operate` · `Recover` |
| `tests.md` | `Dry Run` · `Failure Tests` |
| `logs/README.md` | (presence required; no section gate) |

`automation.md` additionally requires filled-in evidence fields inside `Trigger`,
`Idempotency`, and `Permissions`: trigger source, trigger frequency, idempotency
key, duplicate handling, read permissions, write permissions, approval gates, and
outputs. An empty section header is a `fix-soon` finding; a missing evidence field
is a `blocker`.

---

## Commands

### `agentic-os automation check`

Validates the automation folder: required files, required sections, and required
evidence fields. Emits YAML findings with severity `blocker` or `fix-soon`.
Exit 0 always (findings are reported but do not cause a non-zero exit).

```bash
agentic-os automation check <domain> <lane> <automation> [--root ~/agentic_os]
```

### `agentic-os automation set-maturity`

Sets the maturity level. Advancing beyond a `SAFE_START` level is gated: if any
`blocker` finding exists, the command raises an error and the level is unchanged.
The old and new levels, and the change, are appended to `00-control-plane/decisions.md`.

```bash
agentic-os automation set-maturity <domain> <lane> <automation> <level> [--root ~/agentic_os]
```

### `agentic-os automation attach`

Links an automation to a project. Writes an entry to the project's `status.md`
(Automation Attachments table) and updates `source-map.md`.

```bash
agentic-os automation attach <domain> <lane> <automation> --project <project> [--root ~/agentic_os]
```

---

## Worked examples (real output)

### automation check — a freshly scaffolded automation

```bash
agentic-os automation check acme marketing weekly_report --root /tmp/aos-validate/root
```

```text
automation: /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report
level: observe
findings:
- severity: blocker
  path: .../weekly_report/inputs.md
  message: required automation file is missing
- severity: blocker
  path: .../weekly_report/outputs.md
  message: required automation file is missing
- severity: blocker
  path: .../weekly_report/runbook.md
  message: required automation file is missing
- severity: blocker
  path: .../weekly_report/tests.md
  message: required automation file is missing
- severity: fix-soon
  path: .../weekly_report/automation.md
  message: 'section needs content: Outputs'
- severity: blocker
  path: .../weekly_report/automation.md
  message: 'missing required evidence: trigger source'
- severity: blocker
  path: .../weekly_report/automation.md
  message: 'missing required evidence: trigger frequency'
- severity: blocker
  path: .../weekly_report/automation.md
  message: 'missing required evidence: idempotency key'
- severity: blocker
  path: .../weekly_report/automation.md
  message: 'missing required evidence: duplicate handling'
- severity: blocker
  path: .../weekly_report/automation.md
  message: 'missing required evidence: read permissions'
- severity: blocker
  path: .../weekly_report/automation.md
  message: 'missing required evidence: write permissions'
- severity: blocker
  path: .../weekly_report/automation.md
  message: 'missing required evidence: approval gates'
- severity: blocker
  path: .../weekly_report/automation.md
  message: 'missing required evidence: outputs'
```

Each `blocker` must be resolved before advancing past `prepare`.

### automation set-maturity — advancing to prepare

```bash
agentic-os automation set-maturity acme marketing weekly_report prepare \
  --root /tmp/aos-validate/root
```

```text
automation: /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report
old_level: observe
new_level: prepare
decision_log: /private/tmp/aos-validate/root/acme/00-control-plane/decisions.md
```

Because `prepare` is a `SAFE_START` level, the command succeeds without requiring
a clean check. Advancing to `propose` or beyond would require all blockers to be
resolved first.

### automation attach — linking to a project

```bash
agentic-os automation attach acme marketing weekly_report \
  --project launch --root /tmp/aos-validate/root
```

```text
automation: /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report
project: /private/tmp/aos-validate/root/acme/02-projects/launch
project_status: /private/tmp/aos-validate/root/acme/02-projects/launch/status.md
source_map: /private/tmp/aos-validate/root/acme/02-projects/launch/source-map.md
```

---

### Running this from Claude vs Codex

- **Claude:** invoke the **`automation-qualifier`** skill (`os-create-automation`
  command) — it walks the readiness checklist, assigns a maturity level, and
  scaffolds the required files.
- **Codex:** run `agentic-os automation check/set-maturity` directly; the
  `domain_or_lane` profile in `config.toml` governs the model and approval policy.

> Same maturity gate, same filesystem layout, same decisions log entry. Only the
> trigger differs.  
> Full mechanics: [13 · Agent Surfaces](13-agent-surfaces.md).

---

## Guardrails & gotchas

- **snake_case enforced.** `weekly-report` is rejected; use `weekly_report`.
- **`--root` defaults to `~/agentic_os`.** Always pass `--root` explicitly in
  scripts to avoid touching the live install.
- **`check` exits 0 even with blockers.** Blockers are findings, not crashes.
  Check the YAML output — do not assume exit 0 means "ready to advance."
- **Filesystem is the source of truth.** Maturity is read from the `Level` field
  in `automation.md`. There is no separate registry or database.
- **Only blockers gate advancement.** `fix-soon` findings do not block
  `set-maturity`. Resolve them before promoting to `execute_approved` or higher.
- **`logs/README.md` is required by `check`.** Create the directory and a minimal
  README before your first `check` run to avoid a spurious blocker.
- **`set-maturity` appends to `decisions.md`.** Every level change is logged to
  `<domain>/00-control-plane/decisions.md` automatically — you get an audit trail
  without doing anything extra.

---

## Related

- [06 · Workflows](06-workflows.md) — the precursor: a workflow must be proven
  before it becomes an automation.
- [08 · Runs & Run Logs](08-runs-and-run-logs.md) — every automation execution
  writes a run log; the evidence that qualifies further advancement.
- [09 · Runtime & Always-On](09-runtime-and-always-on.md) — how the runtime layer
  dispatches scheduled automations.
- [10 · Events & Chains](10-events-and-chains.md) — event-triggered automations
  and chain reactions.
- [16 · Health, Doctor & Validation](16-health-doctor-validation.md) — `automation
  check` is one node in the broader validation graph.
- [17 · CLI Reference](17-cli-reference.md) — full flag listing for all
  `automation` subcommands.
- Atlas: [Architecture](../.agentic-atlas/architecture/system-architecture.md) ·
  [Gap Register](../.agentic-atlas/gap-register.md)
