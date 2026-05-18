# Example Domain: Candidate Pipeline

Candidate pipeline workflows often need Notion as the cockpit and a database-backed active state plane for matching, dedupe, sync, and event history.

## Suggested Lanes

- `operations`
- `sales`
- `support`
- `data`

## First Workflows

| Workflow | Purpose |
| --- | --- |
| `lead_or_candidate_intake` | Capture external inputs and normalize them into structured records. |
| `matching_review` | Analyze fit, ranking, missing data, and recommended next action. |
| `meeting_notes_to_actions` | Convert client conversations into tasks, risks, and decisions. |
| `automation_build` | Build client-specific automations with approval gates. |

## Storage Bias

Use a database for active records and matching logic. Use Notion for operator visibility, approvals, and summaries.
