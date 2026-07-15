---
name: agentic-os-operating-contract
description: Apply the shared Agentic OS routing, context, tool-use, workflow, automation, and closeout contract across Claude and Codex.
---

# Agentic OS Operating Contract

Use this skill before acting on any Agentic OS request: an OS domain, project,
workflow, automation, run, skill, tool route, control-plane item, or related
repository task. It governs ordinary conversations as well as explicit runs.

## Operating loop

1. Classify the request before selecting tools or changing state. Identify the
   domain, project, workflow, automation, or run it belongs to. Do not create a
   parallel ad-hoc process when a routed capability already owns the work.
2. For non-trivial investigation, query Genome's Brain with `memory_read` when
   that tool is available. Treat retrieved memory as context, then verify any
   drift-prone fact against the active source, registry, receipt, or runtime.
3. Load the nearest applicable `AGENTS.md`, then its routed `ROUTER.md`,
   `CONTEXT.md`, `RULES.md`, and `TOOLS.md`. Follow their load boundaries; do
   not bulk-load unrelated domains or historical logs. Repeat after routing into
   a narrower domain, workflow, automation, or project.
4. Build the minimum context packet from the active source of truth, the latest
   verified receipt or run state, and only the relevant memory. Chat recap is
   not a substitute for those sources.
5. Follow the provider order and write boundaries in the active `TOOLS.md`.
   Verify the target workspace, account, project, and permission before an
   external write. Preserve explicit approval requirements; never infer approval
   from a request to investigate, report, or draft.
6. For a workflow or automation, use its runbook and state contract. Respect
   its declared mode, trigger, guardrails, idempotency key, and receipt surface.
   A conversational request does not authorize creating a schedule, changing a
   trigger, or executing an external side effect outside that contract.
7. Keep evidence in the routed artifact or run-log surface. For tests, CI,
   watchers, and large logs, report receipt-backed outcomes and blockers rather
   than streaming raw output into chat.
8. Before closeout, validate proportionately, update the owning local state or
   run record, and write a durable `memory_write` learning for substantive,
   non-obvious outcomes when the memory tool is available. Clearly separate
   verified facts, inference, and outstanding blockers.

## Fallbacks

- If the routed files, source root, required tool, or memory plane are not
  available, say exactly which prerequisite is unavailable and continue only
  with safe read-only work that does not pretend the contract was loaded.
- If a request is outside Agentic OS scope, return to the harness's normal
  behavior; this skill does not impose OS process on unrelated conversation.

