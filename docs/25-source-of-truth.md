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
| Control-plane `state.db` | Canonical lifecycle and attention | Work identity, lifecycle, attention, and resume references, mutated through `agentic-os work`. |
| Work-item packets | Durable execution evidence | Plans, worklogs, source references, receipts, decisions, and validation evidence. |
| Library source / installed manifests | Reusable definitions / selected installed revision | `object.yml` definitions and entrypoints; generated indexes are projections. |
| Notion | Operator cockpit | Human-readable reports, dashboards, status summaries, review surfaces. |
| Linear | Product specifications and tracker for Agentic OS work | Issue identity, problem/scope, acceptance criteria, dependencies, and project rollups. |
| Jira | Domain tracker for Jira-owned projects | Jira issue workflow, customer/support work, LOS engineering tickets. |
| GitHub | Code review and CI truth | Branches, PRs, checks, review comments, merge history. |

If two systems disagree, start from the filesystem receipts and the latest live
tracker/PR state. Do not infer success from stale memory or old reports.

---

## Work State And Packet Evidence

Each non-trivial unit of work should have a local packet:

```text
<root>/domains/<domain>/02-projects/<project>/work-items/<MMDDYY-NNN_slug>/
```

The packet path stays stable while lifecycle state and attention change in
`harness/shared_factory/00-control-plane/state.db`. Older numbered work-item
lanes such as `01-intake/` and `02-active/` are compatibility inputs only;
terminal retention may later move a packet to `work-items/99-archived/`.

Change lifecycle and attention through `agentic-os work`. Read
`harness/shared_factory/00-control-plane/active-now.json` for the generated active
projection; do not edit it or infer state from packet folders, tracker status,
branches, or worktrees.

The packet retains:

- A referenced copy of tracker scope in `SPEC.md`, plus `PLAN.md`, `NEXT.md`,
  `WORKLOG.md`, and closeout notes. Keep new specifications and acceptance
  criteria in the owning Jira or Linear item.
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

## Linear Owns Product Specifications And Tracking

For Agentic OS work, Linear owns the product specification and visible product
queue. The local packet retains implementation evidence, and `state.db` owns
local lifecycle/attention. Provider status is advisory for content readiness;
read the actual scope, acceptance behavior, and dependencies before delivery.

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
- treat personal or operator-private repositories as unavailable to
  contributors who only have access to an organization's shared repositories,
- require organization pull requests, issues, comments, and documentation to
  not name, link to, or depend on those private repositories,
- allow private automation pull requests to reference team-accessible
  functionality only when the behavior is scoped to the owning domain,
  project, or program and is not an organization runtime or delivery
  dependency,
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
