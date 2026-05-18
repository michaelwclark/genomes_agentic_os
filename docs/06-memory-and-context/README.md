# Memory And Context

Memory is a retrieval aid. It is not the only source of truth.

The OS should make context cheap to reconstruct by storing stable, small context packs for each domain, workflow, and active work item.

## Context Pack Types

| Pack | Purpose |
| --- | --- |
| Domain context | Business boundaries, systems, credentials policy, stakeholders, and operating rules. |
| Project context | Repo paths, commands, testing rules, deployment notes, and architecture links. |
| Workflow context | The exact process, inputs, outputs, and validation rules for a workflow. |
| Work item context | Current task state, links, prior attempts, decisions, and next action. |
| Run context | What a specific agent run loaded, changed, validated, and produced. |

## Context Pack Standard

Context packs should be:

- Short enough to load directly.
- Linked to primary sources.
- Updated when decisions change.
- Split by operating boundary.
- Written for agents, not as narrative documentation.

## Memory Policy

Use memory for:

- Stable preferences.
- Repeated repo facts.
- Known failure modes.
- Proven workflow shortcuts.
- Durable client operating rules.

Do not use memory as the only place for:

- Active task state.
- Approval decisions.
- Secrets.
- Source files.
- Large meeting transcripts.
- Full Slack threads.

## New Chat Bootstrapping

When a new chat starts with "Here is a Jira, let's build it", the agent should:

1. Identify the domain from Jira/repo/client context.
2. Load the domain context pack.
3. Load the relevant workflow spec.
4. Create or update the work item.
5. Build a task-specific context pack.
6. Start the workflow run.
