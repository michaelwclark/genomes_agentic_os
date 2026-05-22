# Universal Agent Brain Convention

Genome's Agentic OS keeps durable operating instructions in a small set of
well-known prompt files. The convention is intentionally portable across Codex,
Claude, local directories, and generated customer OS installs.

## File Roles

| File | Scope | Harness | Role |
| --- | --- | --- | --- |
| `AGENTS.md` | universal entry point | Codex and compatible agents | Points the agent to the local router, safety rules, and task-specific context loading order. |
| `CLAUDE.md` | Claude entry point | Claude | Mirrors the same routing contract as `AGENTS.md` while allowing Claude-specific packaging notes. |
| `BRAIN.md` | universal operating brain | all harnesses | Holds stable behavior, values, vocabulary, and reusable decisions that should not be duplicated into every entry file. |
| `ROUTER.md` | local routing map | all harnesses | Chooses the domain, lane, workflow, automation, source, and output location for the active request. |
| `CONTEXT.md` | local room context | all harnesses | Describes how work inside this directory should be understood before acting. |
| `MEMORY.md` | durable local memory pointer | all harnesses | Describes what may be remembered, where memory should be written, and what must not be stored. |
| workflow-local files | task execution packet | all harnesses | Provide the concrete runbook, acceptance criteria, output contract, and closeout expectations for a specific workflow. |

`BRAIN.md`, `ROUTER.md`, `CONTEXT.md`, and `MEMORY.md` are universal. `AGENTS.md`
and `CLAUDE.md` are harness entry files that should route into the same universal
files instead of carrying independent copies of the operating system.

## Prompt Stitching Order

When an agent starts in a nested directory, it should stitch context from broad
to narrow and stop as soon as the request has enough evidence to proceed:

1. Global harness entry file in the user's tool runtime.
2. Agentic OS root `BRAIN.md`, `ROUTER.md`, `CONTEXT.md`, and `MEMORY.md`.
3. Customer OS root files when operating inside a customer install.
4. Domain or lane `ROUTER.md`, `CONTEXT.md`, and `MEMORY.md`.
5. Workflow or automation files named by the router.
6. Run-local artifacts, source links, and acceptance criteria for the active task.

The narrower file may add constraints, source links, and output requirements. It
should not silently weaken approval rules, security constraints, or customer
boundaries declared by a broader file.

## Universal Versus Harness-Specific

Universal files:

- `BRAIN.md` records durable behavior that applies to every agent.
- `ROUTER.md` decides where work belongs.
- `CONTEXT.md` explains local operating assumptions.
- `MEMORY.md` defines memory capture and refresh rules.

Harness-specific files:

- `AGENTS.md` is the Codex-compatible discovery surface.
- `CLAUDE.md` is the Claude discovery surface.

Generated files:

- Root, domain, workflow, and automation prompt files may be generated from
  `templates/agent-config/`.
- Generated files should keep a short managed section and leave local notes
  outside that section.
- Regeneration must preserve local edits unless an operator approves a diff.

## Migration Guidance

Use this sequence when an existing OS has duplicated instructions:

1. Move repeated behavior, values, terminology, and safety rules into
   `BRAIN.md`.
2. Leave `AGENTS.md` and `CLAUDE.md` as short harness entry files that point to
   `BRAIN.md`, `ROUTER.md`, `CONTEXT.md`, and `MEMORY.md`.
3. Move directory-specific routing decisions into `ROUTER.md`.
4. Move directory-specific operating context into `CONTEXT.md`.
5. Move durable memory policy into `MEMORY.md`.
6. Keep workflow acceptance criteria in workflow files instead of root prompt
   files.

Do not merge private customer details into shared templates. Customer-specific
facts belong in the customer OS root, domain context, source maps, or workflow
artifacts.

## Nested Example

For a request made inside this workflow directory:

```text
~/agentic_os/acme/03-workflows/operations/monthly_close/
```

The stitched context should look like:

```text
~/.codex/AGENTS.md
~/agentic_os/BRAIN.md
~/agentic_os/ROUTER.md
~/agentic_os/CONTEXT.md
~/agentic_os/MEMORY.md
~/agentic_os/acme/BRAIN.md
~/agentic_os/acme/ROUTER.md
~/agentic_os/acme/CONTEXT.md
~/agentic_os/acme/MEMORY.md
~/agentic_os/acme/03-workflows/operations/monthly_close/workflow.md
~/agentic_os/acme/03-workflows/operations/monthly_close/context-pack.md
~/agentic_os/acme/03-workflows/operations/monthly_close/runbook.md
```

If a file is missing, the agent should continue with the next available file and
record the gap in the run log or closeout notes.

## Precedence

| Rule Type | Precedence |
| --- | --- |
| Safety, approval, and secrets rules | Strictest rule wins. |
| Routing and output destination | Narrowest applicable router wins. |
| Terminology and style | Narrowest context wins unless it conflicts with customer or source terminology. |
| Memory capture | Strictest privacy rule wins. |
| Tool availability | Runtime config wins; prompt files may request tools but cannot assume unavailable tools exist. |

This convention keeps the operating brain reusable while allowing every room,
workflow, and automation to add exactly the local context it needs.
