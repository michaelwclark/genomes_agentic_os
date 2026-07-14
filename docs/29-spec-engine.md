# 29 · Spec Engine

> **Purpose:** provide one configurable idea-to-built workflow for software work,
> regardless of whether it starts as an idea, ticket, backlog item, feature, bug,
> Jira issue, or Linear issue.
>
> **You'll use:** `/add-spec`, the `spec-engine` skill, `agentic-os spec ...`,
> and layered `spec_engine` policy.

---

## One Work Object

A **Spec** is the canonical unit of future or active software work. Provider
records and filesystem packets are representations of that Spec, not competing
lifecycle objects.

| Concern | Canonical values |
| --- | --- |
| Type | `bug`, `feature`, `config` |
| Status | `idea`, `grooming`, `blocked`, `ready`, `in_progress`, `built` |
| Adapter | `filesystem`, `linear`, `jira` |
| Disposition | active, cancelled, duplicate, wont-do, or archived metadata; never a substitute for `built` |

`blocked` retains `blocked_from`; transitioning to `resume` restores that prior
status. This avoids guessing whether unblocked work returns to grooming, ready,
or implementation.

## Policy And Authority

Spec Engine configuration uses this precedence, from lowest to highest:

1. shipped defaults;
2. installed OS root;
3. domain;
4. project;
5. explicit invocation override.

Policy selects content authority, lifecycle authority, adapters, provider
mapping, placement, and approval gates. Filesystem always retains local
identity, provenance, and receipts, even when Jira or Linear owns lifecycle
state.

Typical profiles:

| Project mode | Content authority | Lifecycle authority | Default placement |
| --- | --- | --- | --- |
| Local/filesystem | filesystem | filesystem | project Spec intake |
| Non-LOS Linear | filesystem | Linear | Linear Backlog |
| LOS Jira | filesystem | Jira | Jira backlog |

LOS active-sprint placement is an explicit override, not an implicit default.
Project policy maps canonical types and statuses to native Jira issue types and
workflow states. It must discover sprint and workflow identifiers instead of
hard-coding them.

## CLI

### Add

```bash
agentic-os spec add <domain> <project> \
  --root ~/agentic_os \
  --title "Improve PR review routing" \
  --summary "Route review work to the correct project and model." \
  --type feature \
  --status idea
```

Optional flags: `--id`, `--adapter filesystem|linear|jira`, and
`--dry-run|--apply`. Type defaults to `feature`; status defaults to `idea`.
Filesystem writes locally by default. External adapter operations plan unless
`--apply` is supplied.

### Show And List

```bash
agentic-os spec show clarks_consulting agentic_harness 042_spec_engine \
  --root ~/agentic_os

agentic-os spec list --root ~/agentic_os \
  --domain clarks_consulting --project agentic_harness \
  --status ready --type feature
```

`show` accepts an optional `--adapter`. `list` accepts optional domain, project,
status, and type filters.

### Transition

```bash
agentic-os spec transition clarks_consulting agentic_harness \
  042_spec_engine grooming --root ~/agentic_os

agentic-os spec transition clarks_consulting agentic_harness \
  042_spec_engine resume --root ~/agentic_os
```

Optional flags: `--adapter filesystem|linear|jira` and `--dry-run|--apply`.
Provider transitions must be followed by readback.

### Sync

```bash
agentic-os spec sync clarks_consulting agentic_harness 042_spec_engine \
  --root ~/agentic_os --adapter linear --apply

agentic-os spec sync los los_django \
  --root ~/agentic_os --all --adapter jira
```

`sync` supports one Spec id or `--all`. It targets Linear or Jira and plans by
default. A retry uses the same provider identity and idempotency key.

### Doctor

```bash
agentic-os spec doctor --root ~/agentic_os
agentic-os spec doctor --root ~/agentic_os \
  --domain los --project los_django --adapter jira
```

Doctor validates policy, adapter availability, mappings, and scoped provider
configuration without creating work.

All commands emit YAML normalized records or receipts suitable for worklogs,
automation, and later UI/API consumers.

## Grooming And Readiness

`/add-spec` is the canonical natural-language intake command. When deeper
definition is requested, the `spec-engine` skill transitions the Spec to
`grooming`, preserves `ORIGINAL_INTENT.md`, searches existing capabilities, and
records one route decision:

- `extend_existing`
- `create_under_existing`
- `create_new`

A ready Spec includes product scope, technical mapping, flow/state behavior,
acceptance criteria, Gherkin, QA/holdouts, rollout/backout, assumptions, open
questions, and projection receipts appropriate to the project policy.

`ready` means the configured implementation and team gates passed.
`in_progress` means implementation started. `built` requires validation evidence
and external-provider readback when a tracker owns lifecycle.

## Compatibility Surface

| Legacy command or skill | Spec Engine behavior |
| --- | --- |
| `/add-bug`, `bug-intake-router` | add with type `bug` |
| `/new-feature`, `/add-feature`, `feature-intake-router` | add with type `feature` |
| `/new-idea` | add with type `feature`, status `idea` |
| `/groom-spec`, `spec-groomer` | add/find then enter grooming mode |
| `/auto-add-spec`, `auto-spec-intake` | automatic match-or-add |
| `/auto-add-feature`, `auto-feature-intake` | automatic match-or-add with type `feature` |

Compatibility adapters call the same engine. They must not create legacy
Notion intake rows, separate idea/feature/bug packets, or alternate status
taxonomies.

## Safety And Recovery

- Search provider identities before create.
- External mutations require `--apply`, idempotency, and readback.
- Provider failure leaves a retryable receipt and never creates a duplicate.
- Do not place local paths, private Notion links, secrets, token names, or
  harness-only details in external systems.
- Notion or Obsidian documentation may link to a Spec, but documentation is not
  a mandatory lifecycle queue.

### Running This From Claude Vs Codex

- **Claude:** use `/add-spec` or invoke the `spec-engine` skill.
- **Codex:** invoke the same `spec-engine` skill or call `agentic-os spec ...`
  directly after loading routed `AGENTS.md` context.

Both harnesses execute the same policy, adapters, lifecycle, and receipts.
