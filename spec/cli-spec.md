# CLI Spec

The CLI should be a scaffold and validation tool first. It does not need to run the whole automation platform in V1.

## Proposed Commands

```text
agentic-os init --target ~/agentic_os
agentic-os domain create <name>
agentic-os workflow create <domain> <lane> <name>
agentic-os automation create <domain> <lane> <name>
agentic-os context build <work-item-id>
agentic-os run-log create <workflow-or-automation>
agentic-os notion scaffold <domain>
agentic-os agents install --codex --claude
agentic-os validate
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
