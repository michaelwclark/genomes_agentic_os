# Workflows

A workflow is a repeatable human-or-agent process with explicit inputs, context, steps, validation, and outputs.

Workflows are used when judgment is required. Automations are used when the decision path is stable enough to run on triggers.

## Required Workflow Sections

Every workflow spec should include:

- Purpose.
- When to use.
- When not to use.
- Inputs.
- Preconditions.
- Context pack requirements.
- Steps.
- Validation.
- Outputs.
- State transitions.
- Failure handling.
- Handoff notes.

## Workflow Execution Standard

Agents executing a workflow must:

1. Confirm the input object and domain.
2. Load the workflow spec.
3. Build the context pack from declared sources.
4. Execute only the allowed steps.
5. Validate against the workflow's acceptance criteria.
6. Write a run log.
7. Update the control plane status.

## Example Workflows

- `feature_dev`: build a feature from Jira/spec to PR.
- `pull_request_review`: review PRs when tagged or requested.
- `production_issue_triage`: track and summarize messy production threads.
- `meeting_notes_to_actions`: convert meeting notes into decisions, tasks, and workflow runs.
- `client_automation_build`: turn a client need into a scoped automation and deployment path.

## Workflow Boundary Rule

If the process changes business state, sends messages, creates tickets, deploys code, or mutates customer data, the workflow must include approval rules.
