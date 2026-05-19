# Genome's Agentic OS

Use this skill when the user asks Codex to operate, scaffold, inspect, or execute work inside a Genome's Agentic OS installation.

## Triggers

- "Here is a Jira, let's build it"
- "Run this workflow"
- "Create a new client OS"
- "Capture this meeting into the OS"
- "Review this PR through the OS"
- "Classify this message and route it"
- "Scaffold a domain/workflow/automation"

## Procedure

1. Locate the OS root. Default to `~/agentic_os` unless the user provides another path.
2. Load root `AGENTS.md`, then the selected domain's `AGENTS.md`.
3. Identify the domain, lane, and work type from the user's input.
4. Load the matching workflow or automation spec from `03-workflows` or `04-automations`.
5. Build or update the context pack.
6. Execute the allowed workflow steps.
7. Validate against the spec.
8. Write or update the run log under `<domain>/06-runs-and-logs/runs/`.
9. Update the control plane if configured and allowed.
10. Report final state, artifacts, validation, and next action.

## Safety Rules

- Do not mutate external systems without matching approval rules.
- Do not store secrets in run logs, Notion, or memory.
- Do not treat memory as the only source of active status.
- Preserve project repo worktree changes that were not made by the current run.
- If the OS root does not exist, offer to scaffold it from this repo.

## Output Contract

When finishing a run, report:

- Domain and workflow used.
- Files or external objects changed.
- Validation performed.
- Run log path.
- Current state.
- Next action.
