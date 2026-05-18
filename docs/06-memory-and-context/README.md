# Memory And Context

Memory is a retrieval aid. It is not the only source of truth.

The OS should make context cheap to reconstruct by storing stable, small context packs for each domain, workflow, and active work item.

The purpose of context packs is not to store everything. It is to make the first five minutes of every agent run predictable.

## Context Pack Types

| Pack | Purpose |
| --- | --- |
| Domain context | Business boundaries, systems, credentials policy, stakeholders, and operating rules. |
| Project context | Repo paths, commands, testing rules, deployment notes, and architecture links. |
| Workflow context | The exact process, inputs, outputs, and validation rules for a workflow. |
| Work item context | Current task state, links, prior attempts, decisions, and next action. |
| Run context | What a specific agent run loaded, changed, validated, and produced. |

## Context Pack Loading Order

Load context from most stable to most specific:

1. Domain context.
2. Workflow or automation spec.
3. Source object.
4. Project or system context.
5. Prior decisions and run logs.
6. Current task constraints.

This prevents a noisy source object from overriding durable operating rules.

## Context Pack Standard

Context packs should be:

- Short enough to load directly.
- Linked to primary sources.
- Updated when decisions change.
- Split by operating boundary.
- Written for agents, not as narrative documentation.

## What Good Context Looks Like

Good context is:

- Short.
- Source-linked.
- Current enough to act on.
- Clear about permissions and limits.
- Clear about where live state lives.
- Explicit about what is unknown.

Bad context is:

- A pasted transcript with no extraction.
- A stale summary with no source link.
- A secret or credential.
- A vague instruction like "handle this normally."
- A one-off preference that should be in a workflow spec.

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

## Run Log Relationship

Run logs are not memory, but they are one of the best sources for future memory. If a run reveals a durable preference, repeated failure mode, or reusable operating rule, promote that learning into the appropriate memory or context pack after the run is complete.

Do not use memory to skip the run log. The run log is the audit record for what happened.
