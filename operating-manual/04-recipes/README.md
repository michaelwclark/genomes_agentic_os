# Recipes

## Add A Project

1. Read root and domain routers.
2. Create `02-projects/<project>/`.
3. Add `project.yml`, `README.md`, `status.md`, `decisions.md`, `source-map.md`, and `artifacts/`.
4. Link related workflows and automations from the project README.
5. Add the project to `00-control-plane/active-work.md`.

## Add A Workflow

```bash
agentic-os workflow create <domain> <lane> <workflow> --root ~/agentic_os
```

Then complete `outcome-brief.md`, `alignment-questions.md`, `prd.md`, `implementation-plan.md`, `dispatch-handoff.md`, and `context-pack.md` before dispatching serious work.

## Add An Automation To A Project

1. Prove the workflow manually with run logs.
2. Create the automation folder.
3. Define trigger, inputs, outputs, permissions, failure modes, and tests.
4. Keep the first maturity level at `observe` or `prepare`.
5. Link the automation from the project status file.

## Build Agent Context Automatically

1. Start from domain `CONTEXT.md` and `REFERENCES.md`.
2. Load project `source-map.md` when a project is involved.
3. Load workflow `context-pack.md` for the selected process.
4. Record loaded sources in the run log.
5. Promote stable new sources back into `REFERENCES.md` or `source-map.md`.

## Update Routing Rules After Adding Items

When a skill creates a project, workflow, or automation, it should update:

| Created Object | Also Update |
| --- | --- |
| Project | `00-control-plane/active-work.md`, domain router if routing changed. |
| Workflow | Lane README, routing rules, project README when linked. |
| Automation | Automation lane README, permissions, project status when linked. |
| Run | Activity log, progress file, metrics when useful. |

## Periodic Cleanup

Run a doctor process on a schedule:

1. Validate structure.
2. Find stale active work.
3. Find workflows without run logs.
4. Find automations without permissions or tests.
5. Find run logs missing final status.
6. Propose archive moves and routing updates.

## Tie To Notion Control Panel

Use Notion for dashboarding and approvals. Keep source files in the OS. Sync IDs and links in `domain.yml`, project metadata, run logs, and source maps.
