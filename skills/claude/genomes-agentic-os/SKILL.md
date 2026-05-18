# Genome's Agentic OS

Use this skill when Claude is asked to operate, scaffold, inspect, or execute work inside a Genome's Agentic OS installation.

## Triggers

- "Here is a Jira, let's build it"
- "Run this workflow"
- "Create a new client OS"
- "Capture this meeting into the OS"
- "Review this PR through the OS"
- "Classify this message and route it"
- "Scaffold a domain/workflow/automation"

## Procedure

1. Locate the OS root. Default to `~/agentic_os` unless another path is provided.
2. Load OS config and domain registry.
3. Identify the domain, lane, and work type.
4. Load the workflow or automation spec.
5. Build or update the context pack.
6. Execute only the allowed workflow steps.
7. Validate against the workflow or automation spec.
8. Write or update the run log.
9. Update the control plane if configured and allowed.
10. Return final state, artifacts, validation, and next action.

## Safety Rules

- Do not mutate external systems without matching approval rules.
- Do not store secrets in run logs, Notion, or memory.
- Do not treat memory as the only source of active status.
- Keep output compatible with Codex's run log and workflow contracts.
- If the OS root does not exist, offer to scaffold it from this repo.

## Output Contract

When finishing a run, report:

- Domain and workflow used.
- Files or external objects changed.
- Validation performed.
- Run log path.
- Current state.
- Next action.
