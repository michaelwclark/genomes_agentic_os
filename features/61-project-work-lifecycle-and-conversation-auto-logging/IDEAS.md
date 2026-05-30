# Ideas

## Conversation Auto Logger

Create a default hook that stores conversation transcripts and extracted tool
use in the routed domain/project/work item.

Primary artifacts:

- `YYYY_MM_DD_<slug>.jsonl`
- `YYYY_MM_DD_<slug>_tool_calls.jsonl`
- `YYYY_MM_DD_<slug>_tool_calls.md`

## Project Work-Item Packets

Make feature-60-style markdown stacks available to every project:

- idea
- spec
- plan
- investigation
- judgment
- QA
- worklog
- summary
- next
- memory

## Lifecycle-Aware Routing

`route` and `context build` should return lifecycle state and required files to
read next. If the user names a numbered feature, the agent should jump straight
to the feature/work item and read `SPEC.md`, `PLAN.md`, `WORKLOG.md`, `NEXT.md`,
and validation files.

## Jira Promotion Policy

Allow projects like LOS Django to say: local idea first, local spec mirror while
drafting, Jira ticket after specified, local validation and transcript evidence
remain in the OS.

## Closeout Gate

Add a hook or command that checks whether substantive work updated `WORKLOG.md`,
`NEXT.md`, validation evidence, and any configured external tracker before the
agent finishes.

## Lifecycle Doctor

Detect work items that are stale, missing required files, stuck in `building`,
marked `finished` without validation, or marked `documented` without memory/docs
updates.
