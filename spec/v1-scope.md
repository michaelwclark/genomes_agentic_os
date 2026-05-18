# V1 Scope

## Build In V1

- Documentation for the operating model.
- Specs for product, architecture, CLI, Notion scaffold, and agent install surfaces.
- Templates for domains, workflows, automations, memory policy, run logs, and approvals.
- Example domain overlays for internal product work, client operations, and candidate pipeline work.
- JSON schemas for validating core objects.
- Claude and Codex skill entrypoints.
- Installable CLI scaffold for base OS roots, domains, workflows, automations, run logs, and V1 validation.
- Installer plan for future Notion scaffolding, context-pack build commands, and Claude/Codex surface installation.

## Do Not Build In V1

- Full web application.
- Full event queue runtime.
- Production database service.
- Complex permissions UI.
- Full migration from all existing projects and automations.
- Automatic mutation of external systems without approval controls.
- Full JSON Schema enforcement for every generated object.
- Notion API page/database creation.
- Claude/Codex skill installation into live harness folders.

## First Pilot

Use internal product work as the first pilot because it has clear recurring loops:

- PR review.
- Production issue tracking.
- Feature development from Jira.
- Release management.
- Meeting notes to action items.

The goal is to prove that context packs, workflows, run logs, and Notion cockpit updates reduce chat drift and repeated context loading.
