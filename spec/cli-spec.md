# CLI Spec

The CLI is a scaffold and validation tool first. It does not run the whole automation platform in V1.

## Implemented V1 Commands

```text
agentic-os init --target ~/agentic_os
agentic-os domain create <name> --root ~/agentic_os
agentic-os workflow create <domain> <lane> <name> --root ~/agentic_os
agentic-os automation create <domain> <lane> <name> --root ~/agentic_os
agentic-os run-log create <domain> <workflow-or-automation> --root ~/agentic_os
agentic-os validate --root ~/agentic_os
```

## Future Commands

```text
agentic-os context build <work-item-id>
agentic-os notion scaffold <domain>
agentic-os agents install --codex --claude
```

## Command Responsibilities

| Command | Responsibility |
| --- | --- |
| `init` | Create the domain-first installed OS tree, root/domain source-of-truth routers, Claude/Codex pointer files, domain context/reference files, numbered domain lanes, and shared runtime templates. |
| `domain create` | Create an additional top-level domain with router, context, references, config, control plane, inbox, projects, workflows, automations, knowledge, run logs, metrics, and archive structure. |
| `workflow create` | Create a workflow folder under `<domain>/03-workflows/<lane>/<workflow>/` with spec, outcome brief, alignment questions, PRD, implementation plan, dispatch handoff, progress, quick reference, state machine, context pack, approval rules, output contract, runbook, examples, and runs. |
| `automation create` | Create an automation folder under `<domain>/04-automations/<lane>/<automation>/` with trigger spec, inputs, outputs, permissions, failure modes, runbook, tests, and logs. |
| `context build` | Assemble a context pack from known inputs and domain rules. |
| `run-log create` | Create a timestamped run folder under `<domain>/06-runs-and-logs/runs/` using the standard template. |
| `notion scaffold` | Create or update control-plane pages/databases. |
| `agents install` | Install Claude/Codex rules and skill entrypoints. |
| `validate` | Validate files against schemas and required fields. |

## CLI Design Rules

- Commands should be safe to rerun.
- Generated files should have stable markers or IDs where updates are expected.
- Never overwrite hand-authored content without an explicit flag.
- Output should identify exactly what changed.
- Validation should fail loudly when required operating fields are missing.

## Installed Shape

```text
~/agentic_os/
  ROUTER.md
  AGENTS.md
  CLAUDE.md
  AGENT.md
  personal/
  clarks_consulting/
  los/
  shared_factory/
  archive/
```

Every domain uses the standard `00-control-plane` through `08-archive` lane structure. Workflows and automations are folders inside `03-workflows` and `04-automations`, not loose root-level files.

## V1 Validation Scope

V1 validation checks the domain-first installed folder shape and parses JSON/YAML files. Full schema enforcement, Markdown section validation, Notion ID verification, and agent-surface installation checks are future work.
