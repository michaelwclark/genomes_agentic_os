# 25 · Source Of Truth Rules

> **Purpose:** decide where work should be created, where status should be
> updated, and which system wins when filesystem, Notion, Linear, Jira, or GitHub
> disagree.
>
> **You'll use:** this guide before creating tracker items, publishing operator
> reports, syncing Notion, opening PRs, or writing external status updates.

---

## Short Version

| Surface | Role | Owns |
| --- | --- | --- |
| Agentic OS filesystem | Canonical work state | Specs, plans, worklogs, receipts, decisions, validation evidence. |
| Notion | Operator cockpit | Human-readable reports, dashboards, status summaries, review surfaces. |
| Linear | Product tracker for Agentic OS work | Issue identity, project/initiative rollups, execution status when configured. |
| Jira | Domain tracker for Jira-owned projects | Jira issue workflow, customer/support work, LOS engineering tickets. |
| GitHub | Code review and CI truth | Branches, PRs, checks, review comments, merge history. |

If two systems disagree, start from the filesystem receipts and the latest live
tracker/PR state. Do not infer success from stale memory or old reports.

---

## Filesystem Is Canonical

Each non-trivial unit of work should have a local packet:

```text
<domain>/02-projects/<project>/work-items/<lane>/<NNN_slug>/
```

The packet owns:

- `SPEC.md`, `PLAN.md`, `NEXT.md`, `WORKLOG.md`, and closeout notes.
- Generated artifacts under `artifacts/`.
- Validation receipts and blocker-grade errors.
- Decisions that future agents must honor.

Notion and trackers can summarize or project this state, but they should not be
the only place where implementation evidence exists.

---

## Notion Is The Operator Surface

Use Notion for pages people read:

- portfolio reports,
- status dashboards,
- daily or weekly summaries,
- run-readiness pages,
- review checklists.

Before writing to Notion, verify the target is Genome's Notion. Do not create a
temporary fallback page in a different workspace.

Notion pages can link to internal OS packets when the page is private to Genome's
workspace. External systems should not receive private Notion URLs.

---

## Linear Is A Projection And Tracker

For Agentic OS work, Linear gives the work a tracker id and visible product queue.
It does not replace the filesystem packet.

Use Linear when:

- an OS work item needs a tracker id for `$auto-dev`,
- work should appear in the product/project backlog,
- parent/child work needs product-level rollup,
- status should be visible outside the local packet.

Do not write unsafe local context to Linear. Intake sync should fail closed before
writing local paths, private Notion URLs, or token-shaped values.

When direct Linear API access cannot see the configured team or project, stop.
Fix the approved token or use a project-approved connector-backed path.

---

## Jira Is For Jira-Owned Domains

Use Jira when the project or customer workflow is already Jira-native. LOS work is
the common example.

Jira updates should be self-contained and free of private Genome Notion links or
local filesystem paths. Use Jira keys, PR URLs, commit hashes, and repo-relative
paths instead.

Do not duplicate a Jira-owned execution item into Linear unless the project has an
explicit projection rule. Otherwise, one piece of work now has two operational
sources of truth.

---

## GitHub Owns PR Readiness

GitHub is the live source for:

- branch contents,
- PR description,
- review threads,
- CI/check status,
- merge state.

When local tests are unavailable or too slow, use watcher artifacts and GitHub
checks as the PR readiness signal. Do not claim CI is green from memory.

---

## External Output Rules

Before writing to Linear, Jira, GitHub, Slack, or email:

- remove local absolute paths,
- remove private Genome Notion URLs,
- remove token-shaped values and env secrets,
- prefer public issue keys, PR URLs, commit hashes, artifact names, or
  repo-relative paths,
- include the newest verified receipt, not an old report.

When in doubt, write the detailed evidence to the local packet and send a compact
external summary.

---

## Conflict Resolution

Use this order:

1. Live runtime or provider state, when the question is about current status.
2. Latest durable receipt in the local packet.
3. Source repository state and GitHub PR/check state.
4. Notion operator report.
5. Memory or prior conversation summary.

If the current state cannot be verified, say that it is unverified and record the
blocker. Do not silently promote stale state into a tracker or report.

---

## Closeout Pattern

At the end of a work item:

- update `WORKLOG.md`,
- update `NEXT.md`,
- update the tracker with a sanitized summary,
- update the Notion operator report if one exists,
- run validation or record the blocker,
- commit and push source changes,
- leave the installed root in a known state.

The same facts should appear at different levels of detail: detailed in the local
packet, readable in Notion, compact in trackers, and evidence-backed in GitHub.
