# 02 Routing And Context Builder

## Table Of Contents

- [Purpose](#purpose)
- [Source And Runtime Boundaries](#source-and-runtime-boundaries)
- [Commands](#commands)
- [Context Packet Shape](#context-packet-shape)
- [How Routing Decides](#how-routing-decides)
- [Operator Flow](#operator-flow)
- [Disposable Validation](#disposable-validation)
- [Failure Behavior](#failure-behavior)
- [Done Signal](#done-signal)

## Purpose

Feature 02 lets an operator ask the OS where work belongs and which files an agent should load. It reduces reliance on chat history by building deterministic routing and context packets from installed runtime files.

Use this guide before dispatching Codex or Claude into a project, workflow, or domain when you need a concrete source list and target path.

## Source And Runtime Boundaries

This repository owns the routing implementation and tests. The installed OS root owns live routers, project records, workflow context packs, active-work rows, and source maps. Routing commands should read from the installed root and print YAML; they should not write Notion or mutate runtime state by default.

## Commands

```bash
agentic-os route "Deploy losmon_replacement to production" --root ~/agentic_os
agentic-os context build --domain los --project losmon_replacement --root ~/agentic_os
agentic-os here route "Summarize active work" --root ~/agentic_os
agentic-os here context build --root ~/agentic_os
```

`route` starts from a request string. `context build` starts from explicit domain/project/workflow arguments. `here` commands infer context from the current directory, either inside the OS root or inside a repository linked from a project source map.

## Context Packet Shape

The command prints YAML with these fields:

```yaml
domain: los
lane: engineering
object_type: project
target_path: /path/to/agentic_os/los/02-projects/losmon_replacement
sources_to_load:
  - /path/to/agentic_os/ROUTER.md
  - /path/to/agentic_os/los/ROUTER.md
approval_risks:
  - production change
known_gaps: []
handoff_prompt: Load the listed sources...
```

Operators should treat `sources_to_load` as the minimum context pack for the next agent. `known_gaps` means a referenced file is missing and should be resolved or acknowledged before dispatch.

## How Routing Decides

Routing uses installed domains, project records, linked repo paths, and request labels. Project matches win when exactly one project matches the request. Domain matches are accepted only when exactly one domain matches. Multiple matches or no matches fail safely.

Approval risks are keyword based. Requests containing words such as `deploy`, `production`, `delete`, `secret`, `billing`, or `customer` surface approval-risk labels in the packet.

## Operator Flow

1. Ensure the project or workflow exists in the installed OS root.
2. Run `agentic-os route` for a request or `agentic-os context build` for explicit context.
3. Review `target_path`, `sources_to_load`, `approval_risks`, and `known_gaps`.
4. Give the next agent the handoff prompt and source list.
5. If routing fails as ambiguous, add the domain/project name or use explicit `context build` arguments.

## Disposable Validation

```bash
TMP_ROOT="$(mktemp -d)/agentic_os"
TMP_REPO="$(mktemp -d)/linked_repo"
uv run agentic-os init --target "$TMP_ROOT"
uv run agentic-os project create los losmon_replacement --root "$TMP_ROOT" --repo "$TMP_REPO" --lane engineering
uv run agentic-os route "Deploy losmon_replacement to production" --root "$TMP_ROOT"
uv run agentic-os context build --domain los --project losmon_replacement --root "$TMP_ROOT"
(
  cd "$TMP_REPO"
  uv run --project /Users/genome/projects/genomes_agentic_os agentic-os here context build --root "$TMP_ROOT"
)
uv run agentic-os validate --root "$TMP_ROOT"
```

## Failure Behavior

Low-confidence routing returns an error instead of guessing. Examples include vague requests such as `Do the thing` or requests that name multiple domains. Use explicit `context build` arguments when the request is intentionally cross-domain.

## Done Signal

Feature 02 is healthy when routing can classify a project request, context build returns exact source files, `here` works from both OS paths and linked repositories, approval risks appear for sensitive requests, ambiguous requests fail safely, and pytest remains green.
