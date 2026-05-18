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
| `init` | Create the installed OS tree and base config. |
| `domain create` | Create a domain folder, domain config, context files, and Notion mapping stub. |
| `workflow create` | Copy workflow template into a lane and register it. |
| `automation create` | Copy automation template into a lane and register it. |
| `context build` | Assemble a context pack from known inputs and domain rules. |
| `run-log create` | Create a run log using the standard template. |
| `notion scaffold` | Create or update control-plane pages/databases. |
| `agents install` | Install Claude/Codex rules and skill entrypoints. |
| `validate` | Validate files against schemas and required fields. |

## CLI Design Rules

- Commands should be safe to rerun.
- Generated files should have stable markers or IDs where updates are expected.
- Never overwrite hand-authored content without an explicit flag.
- Output should identify exactly what changed.
- Validation should fail loudly when required operating fields are missing.

## V1 Validation Scope

V1 validation checks the installed folder shape and parses JSON/YAML files. Full schema enforcement, Markdown section validation, Notion ID verification, and agent-surface installation checks are future work.
