---
name: spec-engine
description: Operate the canonical Agentic OS Spec lifecycle across filesystem, Linear, and Jira adapters. Use for add-spec, ideas, tickets, backlog items, bugs, features, config work, grooming, transitions, sync, or Spec Engine diagnosis.
---

# Spec Engine

Use this skill whenever work should be tracked or defined for agentic delivery.
Ideas, tickets, Jira issues, Linear issues, backlog items, features, bugs, and
configuration changes are all canonical Specs with different type, status,
scope, policy, and adapter metadata.

## Canonical Model

Types:

- `bug`
- `feature`
- `config`

Statuses:

- `idea`
- `grooming`
- `blocked`
- `ready`
- `in_progress`
- `built`

Cancellation, duplication, rejection, and archival are dispositions, not
delivery statuses. Never translate them to `built`. A blocked Spec retains
`blocked_from`; use `resume` to return to that status.

## Startup

1. Load the routed root, domain, project, and active Spec context.
2. Load `harness/shared_factory/00-programs/spec_grooming/`; this legacy path
   contains the canonical `spec_engine` OSProgram during migration.
3. Resolve policy in this precedence order:
   shipped defaults → root → domain → project → explicit invocation override.
4. Confirm content authority, lifecycle authority, selected adapters, and any
   team gates before writing.

## Commands

Add a Spec:

```bash
agentic-os spec add <domain> <project> \
  --root <root> --title "<title>" --summary "<raw intent>" \
  [--type <bug|feature|config>] \
  [--status <idea|grooming|blocked|ready|in_progress|built>] \
  [--id <stable-id>] [--adapter <filesystem|linear|jira>] \
  [--dry-run|--apply]
```

Inspect normalized records:

```bash
agentic-os spec show <domain> <project> <spec_id> --root <root> [--adapter <filesystem|linear|jira>]
agentic-os spec list --root <root> [--domain <domain>] [--project <project>] [--status <status>] [--type <type>]
```

Transition or resume:

```bash
agentic-os spec transition <domain> <project> <spec_id> <status|resume> \
  --root <root> [--adapter <filesystem|linear|jira>] [--dry-run|--apply]
```

Synchronize lifecycle authority to a tracker:

```bash
agentic-os spec sync <domain> <project> [spec_id] \
  --root <root> [--all] --adapter <linear|jira> [--apply]
```

Diagnose policy and adapter configuration:

```bash
agentic-os spec doctor --root <root> [--domain <domain>] [--project <project>] [--adapter <filesystem|linear|jira>]
```

Commands emit normalized YAML records or receipts. Preserve receipts with the
Spec worklog when they change external state. The filesystem adapter records
non-dry-run receipts in `artifacts/spec-receipts/` and links verified provider
identities back to the local record.

## Intake And Grooming Loop

1. Search scoped Specs and provider identities before adding new work.
2. Preserve original user language and explicit non-goals.
3. Add the Spec with the narrowest correct domain/project and canonical type.
4. If grooming is requested, transition to `grooming`, write
   `ORIGINAL_INTENT.md`, and run existing-capability discovery.
5. Record exactly one route decision: `extend_existing`,
   `create_under_existing`, or `create_new`.
6. Complete product scope, technical mapping, flow/state, acceptance criteria,
   Gherkin, QA/holdouts, rollout/backout, assumptions, and open questions.
7. Transition to `ready` only after project readiness and team gates pass.
8. Transition to `in_progress` when implementation begins and to `built` only
   after validation evidence and provider readback.

## Adapter Rules

### Filesystem

Always retain a local identity/provenance envelope and receipts. Filesystem-only
projects require no tracker. Local files may own both content and lifecycle.

### Linear

Use for configured non-LOS backlogs and lists. Default new work to Backlog.
Map `ready`, `in_progress`, and `built` through project policy. Represent
`blocked` with a configured native state or a blocked label while preserving
the prior state.

### Jira

Use for configured LOS/team work. Default placement is the Jira backlog.
Current-sprint placement requires an explicit permitted override. Map `bug`,
`feature`, and `config` to project-configured issue types, and discover workflow
and sprint identifiers rather than hard-coding them.

## Safety And Completion

- External adapters plan unless `--apply` is supplied.
- Every external mutation must be idempotent and followed by readback.
- On provider failure, retain a retryable receipt; do not create a duplicate.
- Verify the selected provider account/workspace before writes.
- Sanitize external text: no local paths, private Notion links, secrets, token
  names, or harness-only details.
- Notion and Obsidian may document a Spec, but neither is an implicit lifecycle
  adapter.
- Completion requires Spec id, canonical status/type, scope, selected authority,
  adapter receipt, external URL when present, and next action.
