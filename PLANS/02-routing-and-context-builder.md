# Feature Spec: Routing And Context Builder

## Status

- Status: ready
- Owner: Genome
- Created: 2026-05-20
- Target OS layer: source package, installed runtime, Codex, and Claude

## Problem

Agents still rely on the user or chat history to know where they are, what domain owns the work, and which files to load. The OS has routers and source maps, but it does not yet assemble the minimal context packet automatically.

## Outcome

From a prompt or current directory, the OS can identify the domain, project, workflow or automation, risk level, required sources, and next file to edit.

## Commands

```bash
agentic-os route "<request>" --root ~/agentic_os
agentic-os context build --domain <domain> --project <project> --workflow <workflow> --root ~/agentic_os
agentic-os here route "<request>"
agentic-os here context build
```

## Context Inputs

- Root `ROUTER.md`.
- Domain `ROUTER.md`, `CONTEXT.md`, and `REFERENCES.md`.
- Domain `00-control-plane/active-work.md`.
- Project `project.yml`, `status.md`, and `source-map.md`.
- Workflow or automation `context-pack.md`.
- Recent relevant run logs.
- Memory policy.

## Context Output

```text
domain:
lane:
object_type:
target_path:
sources_to_load:
approval_risks:
known_gaps:
handoff_prompt:
```

## Required Side Effects

- Write context output to the run log when a run exists.
- Optionally write or refresh the workflow `context-pack.md` only when explicitly requested.
- Keep the default route command read-only.

## Out Of Scope

- LLM summarization service.
- Notion writes.
- Vector search implementation.

## Acceptance Criteria

- Route can classify a request using routers without chat history.
- Context build returns exact files and source links.
- `here` detects an OS path or linked work repo and reduces repeated arguments.
- Commands fail safely when routing confidence is low.
- Tests cover OS cwd, project cwd, ambiguous requests, and approval-risk output.

## Validation

- `pytest -q`
- Manual route checks from `~/agentic_os`, `~/agentic_os/los`, and a linked repo under `~/projects`.
