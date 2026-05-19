# Concepts

## What The OS Is

The OS is a filesystem-backed operating layer for agentic work. Chat is the interface. Files are the durable source of truth.

## Core Objects

| Object | Meaning |
| --- | --- |
| Root | Domain map and install entry point. |
| Domain | Operating boundary with context, rules, workflows, automations, and logs. |
| Project | Active outcome inside a domain. |
| Workflow | Repeatable process that still needs judgment. |
| Automation | Repeatable process with a trigger, guardrails, permissions, and logs. |
| Run | One execution of a workflow, automation, or skill. |
| Skill | Harness-level behavior package that knows how to operate a part of the OS. |
| Command | Short reusable prompt or CLI command that invokes an OS behavior. |

## Source Of Truth

The source package owns templates and default docs. The installed OS owns live state. Notion is a control panel, not the runtime database.

## Promotion Loop

Good runs should promote durable learning back into the OS:

```text
run evidence -> progress -> domain context -> workflow template -> automation -> metrics
```
