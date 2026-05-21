# Harness Commands And Skills

The installed OS includes command prompts and skill specs under:

```text
shared_factory/05-knowledge/commands/
shared_factory/05-knowledge/skills/
```

These are source-of-truth local copies. Harness-specific installers can later copy or link them into Claude and Codex surfaces.

## Command Pack

| Command File | Use |
| --- | --- |
| `os-route.md` | Classify a request and choose the domain, lane, and object. |
| `os-discover-rooms.md` | Ask customer/operator discovery questions and generate room/profile inputs. |
| `os-create-workflow.md` | Create and complete a workflow contract. |
| `os-create-automation.md` | Convert a proven workflow into guarded automation. |
| `os-run-log.md` | Create or complete a run log. |
| `os-capture-plan.md` | Capture future OS plans, ideas, and customer patterns in the right place. |
| `os-update.md` | Add missing package assets without overwriting runtime files. |
| `os-doctor.md` | Validate structure and find stale or incomplete state. |
| `os-sync-notion.md` | Prepare Notion control-plane sync. |

## Skill Pack

| Skill | Use |
| --- | --- |
| `os-navigator` | Load the right routers and pick the next file. |
| `room-builder` | Turn discovered customer/operator rooms into context, routing, references, and skill maps. |
| `domain-setup` | Fill domain context, references, and control plane. |
| `workflow-builder` | Build workflow folders and required docs. |
| `automation-qualifier` | Decide whether a workflow can become automation. |
| `context-pack-builder` | Build minimum useful agent context. |
| `run-logger` | Record execution evidence and next action. |
| `learning-promoter` | Promote durable learning to docs, routers, templates, or context. |
| `os-doctor` | Validate, clean, and propose repairs. |
