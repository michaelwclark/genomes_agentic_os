# Documentation Index

These docs explain how to structure, install, and operate an agentic operating system. They are written as implementation guidance for humans and agents that need to run the same process repeatedly without rediscovering context.

Start with the README when you need the product pitch and quick install path. Use this index when you need the operating manual.

## Reading Path

| If You Need To Understand | Read |
| --- | --- |
| Why the OS exists | [00 - Rationale](00-rationale/README.md) |
| How work moves through the OS | [01 - Operating Model](01-operating-model/README.md) |
| Where domains, workflows, automations, and run logs live | [02 - Information Architecture](02-information-architecture/README.md) |
| How the CLI scaffolds a working install | [10 - CLI And Install](10-cli-and-install/README.md) |
| How Notion fits without becoming the runtime database | [03 - Control Plane](03-control-plane/README.md) |
| How to author executable workflow specs | [04 - Workflows](04-workflows/README.md) |
| How to author guarded automations | [05 - Automations](05-automations/README.md) |
| How memory and context packs reduce prompt mass | [06 - Memory And Context](06-memory-and-context/README.md) |
| How Claude and Codex should execute the same process | [07 - Agent Surfaces](07-agent-surfaces/README.md) |
| When filesystem, Notion, or a database should own state | [09 - Storage Model](09-storage-model/README.md) |

## Sections

| Doc | Purpose |
| --- | --- |
| [00 - Rationale](00-rationale/README.md) | Why this exists and what improvement it should create. |
| [01 - Operating Model](01-operating-model/README.md) | The loop every domain, workflow, and automation follows. |
| [02 - Information Architecture](02-information-architecture/README.md) | How to organize domains, lanes, workflows, and automations. |
| [03 - Control Plane](03-control-plane/README.md) | How Notion acts as the human cockpit. |
| [04 - Workflows](04-workflows/README.md) | How reusable workflow specs should be written and executed. |
| [05 - Automations](05-automations/README.md) | How recurring and event-driven automations should be specified. |
| [06 - Memory And Context](06-memory-and-context/README.md) | How agents should build and reuse context without bloating prompts. |
| [07 - Agent Surfaces](07-agent-surfaces/README.md) | How Claude and Codex should be installed into the OS. |
| [08 - Client OS Patterns](08-client-os-patterns/README.md) | How client-specific systems differ without changing the core model. |
| [09 - Storage Model](09-storage-model/README.md) | Filesystem, Notion, database, and vector/memory boundaries. |
| [10 - CLI And Install](10-cli-and-install/README.md) | How to install the CLI, scaffold an OS root, and smoke-test the result. |
| [Diagrams](diagrams/README.md) | SVG diagrams for value flow, lifecycle, data flow, and storage boundaries. |

## Object Vocabulary

| Object | Meaning |
| --- | --- |
| Domain | Operating boundary with its own context, workflows, automations, approvals, and Notion mapping. |
| Lane | Functional grouping inside a domain, such as engineering, support, operations, or finance. |
| Workflow | Repeatable process for judgment-heavy work. |
| Automation | Triggered workflow with permissions, idempotency, and audit requirements. |
| Context pack | Compact source-linked facts an agent loads before execution. |
| Run log | Durable evidence of one workflow, automation, or skill execution. |
| Control plane | Human-facing cockpit for intake, status, approvals, and dashboards. |

## Operating Promise

Every installed OS should make these questions cheap to answer:

1. What is this work item?
2. Which domain owns it?
3. Which workflow or automation should run?
4. What context is required?
5. What actions are allowed?
6. What validation proves the result?
7. What state changed?
8. What needs approval or follow-up?
