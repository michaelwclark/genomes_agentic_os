# Work Lifecycle Standard

New work uses one date-prefixed packet directly under the project's canonical
`work-items/` root. Lifecycle state lives in the tracker and state plane, not
in a numbered subfolder. Terminal packets remain in place for the configured
retention period, then the nightly `work_item_archive` health automation moves
them to `work-items/99-archived/` without deleting evidence. Agents must search
that archive before creating work for a ticket that has returned.

**Source of truth:** `harness/rules/work-lifecycle-standard.md` (repo canonical).
Instance copy lives at the same path under `/Users/genome/agentic_os/`.
Last updated: 2026-07-07.

---

## 1. The Four Phases

Work items move through four phases. The **canonical state names** below are the
only values stored in the SQLite work-item registry or emitted by resolvers.
Filesystem folders, SPEC frontmatter, Jira, Linear, and other external surfaces
are observations or projections, not state truth.

### Phase 1 — Capture

| Canonical state | Meaning |
|---|---|
| `captured` | Idea or need recorded; not yet assessed for build-readiness. |
| `triaged` | Reviewed, categorised, and accepted for grooming; not yet specified. |

Items in this phase are **not ready for auto-dev**. The grooming route is
`spec-intake` (single item) or `aos-product-orchestrator` (program or batch).

### Phase 2 — Groom

| Canonical state | Meaning |
|---|---|
| `specified` | SPEC.md exists with full acceptance criteria; ready to be reviewed for build. |

`specified` is groom-phase complete. It is NOT a build state. auto-dev requires
`--allow-specified` to start from here; the preferred path is promoting to `ready`
first.

### Phase 3 — Build

| Canonical state | Meaning |
|---|---|
| `ready` | Grooming signed off; tracker item minted; auto-dev may start unconditionally. |
| `building` | Implementation in progress (auto-dev has claimed the item). |
| `validating` | PR open, CI/Copilot/finishing-review gate running. |
| `blocked` | Stalled — product decision, infrastructure, or external dependency. Always carries a receipt. |

### Phase 4 — Close

| Canonical state | Meaning |
|---|---|
| `finished` | Implementation merged; work is done. |
| `documented` | Post-ship write-up, runbook, or Notion projection complete. |
| `archived` | Item closed without shipping (dropped, cancelled, or superseded). |

> **Note on `blocked`:** this state is non-terminal and non-ordinal. It is
> reachable from any build-phase state and exits to the state it paused. The
> resolver treats it like `building` for gate purposes.

---

## 1a. Canonical Work State And Stable Artifact Destination

The SQLite database at
`harness/shared_factory/00-control-plane/state.db` is authoritative for both
lifecycle `state` and attention (`active`, `queued`, `parked`, or `closed`). Read
`active-now.json` first for compact context and query the database for detail.
Never infer active work by counting folders or checking Jira, Linear, branches,
or worktrees.

Packet paths are stable and do not change when state changes:

```
<OS_ROOT>/domains/<domain>/projects/<project>/work-items/<work-item-id>/
```

Legacy `01-intake`, `02-active`, and `03-complete` folders are import and
compatibility surfaces only. Do not move a packet between them to express
state. During layout-v2 migration, their contents remain readable until every
writer uses `agentic-os work` and stable packet paths.

**Packet artifacts** that belong in the OS work item (not the code repo):
`PROMPT-PACK.md`, `WORKLOG.md`, `JIRA.md`, `PR.md`, `QA_HANDOFF.md`, `SPEC.md`,
`PLAN.md` / `implementation-plan.md`, `DECISIONS.md`, review packets, handoff
packs, and `NEXT.md`.

**`.features/` is a mirror, never the source of truth.** A `.features/<ticket>/`
directory inside a code repository (e.g.
`/Users/genome/projects/los/app/los-app-los-django/.features/…`) is at most a
disposable mirror, kept only when existing repo tooling requires it. Do not treat
it as canonical, and do not write lifecycle/handoff packets there. Disposable raw
evidence (watcher state files, CI logs, screenshots) may remain in `.features/`.

The `work-item-routing-guard` PostToolUse hook enforces this: writing a
packet-shaped file into a code-repo `.features/` directory emits an advisory
naming the canonical OS destination. It does not fire on disposable raw evidence.

---

## 2. auto-dev Stage Gate

```
auto-dev may only START items whose canonical state is:
  - ready           → proceeds unconditionally
  - building        → resumes (already claimed)
  - validating      → resumes (PR already open)
  - blocked         → check receipt; resolve blocker first
  - specified       → proceeds only with --allow-specified flag
```

Items at `captured` or `triaged` **must go to grooming first** — they are not
build-ready. The resolver exits 2 and prints the grooming route.

Items at `specified` without `--allow-specified` exit 2 and print:

```
State is 'specified' (groom-phase complete, not yet promoted to ready).
Options:
  1. Add --allow-specified to start anyway.
  2. Promote the registry row to state: ready with agentic-os work set, then re-run.
```

Items at terminal close states (`finished`, `documented`, `archived`) exit 2
with a note that the item is closed.

---

## 3. State And Attention Mapping Table

One row per canonical state. External surface values shown are the **closest
current label** — they are not renames (Notion DB options are not renamed tonight;
that rename is follow-up work).

| Canonical state | Default attention | Legacy lane | Work Intake status | Linear state | Runner state |
|---|---|---|---|---|---|
| `captured` | `queued` | `01-intake` | `inbox` | Backlog | — |
| `triaged` | `queued` | `01-intake` | `triaged` | Backlog | — |
| `specified` | `queued` | `02-active` | `spec-ready` | Backlog/Todo | — |
| `ready` | `queued` | `02-active` | `queued` | Todo | `discovered` |
| `building` | `active` or `parked` | `02-active` | `in-progress` | In Progress | `implementing` |
| `validating` | `active` or `parked` | `02-active` | `in-progress` | In Review | `pr_open` / watches |
| `blocked` | `active` or `parked` | `02-active` | `blocked` | Blocked | `blocked` |
| `finished` | `closed` | `03-complete` | `done` | Done | `merged` |
| `documented` | `closed` | `03-complete` | `done` | Done | `merged` |
| `archived` | `closed` | `03-complete` | `dropped` | Cancelled | `abandoned` |

**Row count: 10.** (One per canonical state.)

### Many-to-one mapping notes

- **DB `in-progress`** covers both `building` and `validating` — the DB has no
  separate "In Review" option tonight. Follow-up: add `in-review` DB option.
- **DB `done`** covers both `finished` and `documented`.
- **DB `dropped`** maps to `archived`. There is no `dropped` canonical state; if
  D10's proposed 12-state list (which adds `queued` and `dropped` as canonical
  states) is adopted later, these cells collapse to 1:1. **Flag: 50/50 — see §5.**
- **DB `queued`** maps to `ready` (not a separate canonical state).
- **Linear states** are project-specific; the values above are the standard Linear
  default set. Override in each project's `dev_factory.tracker.linear.workflow`.

---

## 4. Conformance Rule

Every project's `config/work-lifecycle.yml` **must** use the 10 canonical state
names and four attention values above. A lane mapping may remain only as a
legacy importer mapping; it must not control current state or packet movement.
When adding or upgrading a project:

```yaml
work_lifecycle:
  states:
    - captured
    - triaged
    - specified
    - ready
    - building
    - validating
    - finished
    - documented
    - blocked
    - archived
  attention_states: [active, queued, parked, closed]
  state_source: harness/shared_factory/00-control-plane/state.db
  active_projection: harness/shared_factory/00-control-plane/active-now.json
```

Use `agentic-os work upsert` for intake and reconciliation, `agentic-os work
set` for state or attention changes, and `agentic-os work active-now` before
loading broad project context. Active items require a resume summary; blocked
items require a blocker reason or receipt.

---

## 5. Open Decisions (50/50 calls)

**D10-A — `queued` and `dropped` as canonical states.**
D10 (023 SPEC decisions log, 2026-07-02) proposed 12 canonical states including
`queued` (between `ready` and `building`) and `dropped` (parallel close path to
`archived`). The existing `work-lifecycle.yml` has 10 states (no `queued`, no
`dropped`), and the task brief says "losmon's already does [conform]", which is
only true for 10. This standard uses 10 states and maps the DB labels instead.
**If D10 was the intended final answer, update this document, add `queued` and
`dropped` to every project's `work-lifecycle.yml`, and recount the table to 12.**

**D10-B — DB rename timing.**
The task brief says do not rename DB options tonight. The mapping table above
captures the current label↔canonical pairing. Rename follow-up: consider
aliasing DB `in-progress`→`building`/`validating`, `queued`→`ready`,
`dropped`→`archived`.
