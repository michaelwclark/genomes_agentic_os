---
name: initiative-context-resume
description: Use when creating, resuming, or maintaining a long-running initiative or subproject in any Agentic OS domain; builds a durable context pack, project index entries, active-work handoff, and validation trail so future agents can discover the right context quickly.
---

# Initiative Context Resume

## Overview

This skill turns a loose long-running initiative into a discoverable Agentic OS work item with enough context for a future agent to resume without reading the whole chat history.

Use it when the user says a subproject, initiative, spec, design effort, Notion project, external planning packet, or ongoing investigation needs to be resumed later, carried across agents, or made easier to find from the OS routing surfaces.

## Completion Standard

A fresh agent starting from the OS root can find the initiative by following normal routing:

1. Root `AGENTS.md` routes to the domain.
2. Domain `active-work.md` points to the project/work item.
3. Project `status.md` and `source-map.md` point to the work item context pack.
4. The work item `CONTEXT.md` states the source of truth, current phase, known decisions, exact must-read artifacts, code anchors, and next actions.

## Workflow

1. Route to the final domain/project layer before writing.
   - Read that layer's `AGENTS.md`, `ROUTER.md`, `CONTEXT.md`, `RULES.md`, and `TOOLS.md` when present.
   - Use project memory retrieval before non-trivial reconstruction.
   - Keep private Notion and local filesystem links inside OS-local context, not external Jira/GitHub/Slack output.

2. Choose the initiative anchor.
   - Prefer an existing project work item when the initiative belongs to a codebase or durable project.
   - Use `spec-intake-router`/`/add-spec` ownership for unbuilt feature/spec work; this skill only adds the durable resume context and indexes.
   - Use `work-items/<date>-<nnn_slug>/` with `--status captured` while it is still planning/spec work.
   - Keep the packet path stable as lifecycle state changes.

3. Build or update the context pack.
   - Preferred command:

```bash
python3 harness/skills/initiative-context-resume/scripts/update_initiative_context.py \
  --project-path <domain>/02-projects/<project> \
  --work-item-id <nnn_slug> \
  --title "<initiative title>" \
  --summary "<one paragraph>" \
  --status captured \
  --phase planning \
  --source "Notion hub=<url>" \
  --artifact "Design package=<path-or-url>" \
  --code-anchor "<repo-relative-or-local-path>:<line>" \
  --decision "<stable decision>" \
  --next-action "<next action>" \
  --active-work-file <domain>/00-control-plane/active-work.md
```

4. Register discovery surfaces.
   - Work item: `CONTEXT.md`, `work.yml`, `SPEC.md`, `PLAN.md`, `DECISIONS.md`, `NEXT.md`, and `WORKLOG.md`; include `QUESTIONS.md` when unresolved questions exist.
   - Project: managed initiative blocks in `status.md` and `source-map.md`.
   - Domain: managed initiative block in `00-control-plane/active-work.md` when that file exists.
   - Optional external docs: link them from `CONTEXT.md`, but do not create external tracker tasks until the user asks.

5. Validate resume discovery.
   - Run the updater twice with the same arguments and confirm it does not duplicate managed blocks.
   - Run a focused search for the title/slug across the root, domain, project, and work item routing surfaces.
   - Confirm the generated `CONTEXT.md` answers: where is the source of truth, what is the current phase, what must be read first, what changed last, and what should happen next.

6. Close out.
   - Record a run log when the turn is substantive.
   - Promote durable, reusable facts to project memory.
   - Report exact files changed and validation performed.

## Context Contract

Load `references/context-contract.md` before changing the convention or when deciding whether a context pack is complete.

## Guardrails

- Do not overwrite human-authored work-item notes wholesale. Update managed blocks or create missing files.
- Do not paste secrets or long private documents into `CONTEXT.md`; link to the approved source instead.
- Treat Notion links as internal unless the user explicitly approves sharing them externally.
- If a project already has a stricter work-item convention, preserve it and add only the missing resume-discovery fields.
