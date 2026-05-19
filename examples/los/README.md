# Example Domain: LOS

LOS work is a strong first pilot because it has repeated daily loops with changing state, code repos, Jira, PRs, releases, support threads, and production safety gates.

## Suggested Lanes

- `engineering`
- `support`
- `operations`

## First Workflows

| Workflow | Purpose |
| --- | --- |
| `feature_dev` | Build from Jira/spec through implementation, validation, and PR. |
| `pull_request_review` | Review tagged PRs with blocker/high-risk focus. |
| `production_issue_triage` | Track messy production threads and preserve evolving context. |
| `release_management` | Prepare and validate release branch or deploy changes. |

## First Automations

| Automation | Level | Purpose |
| --- | --- | --- |
| `tagged_pr_review` | `prepare` | Detect PR tags, build context, draft review output. |
| `production_thread_intake` | `prepare` | Capture threads, classify incidents, maintain issue cases. |
| `jira_to_context_pack` | `prepare` | Start feature context from a Jira ticket. |

## Storage Note

Start with filesystem and Notion for the pilot. Move production issue and PR-cycle active state to a database when automated concurrency or repeated state transitions become painful.
