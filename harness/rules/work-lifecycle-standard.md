# Work Lifecycle Standard

**Source of truth:** `harness/rules/work-lifecycle-standard.md` (repo canonical).
Instance copy lives at the same path under `/Users/genome/agentic_os/`.
Last updated: 2026-07-02.

---

## 1. The Four Phases

Work items move through four phases. The **canonical state names** below are the
only names that may appear in `work-lifecycle.yml`, SPEC.md frontmatter `state:`
fields, and resolver/tool output. Do not use synonyms, abbreviations, or status
labels from external surfaces — those map *onto* canonical states (see §3).

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
  2. Promote the packet to state: ready in SPEC.md and filesystem lane, then re-run.
```

Items at terminal close states (`finished`, `documented`, `archived`) exit 2
with a note that the item is closed.

---

## 3. Surface Mapping Table

One row per canonical state. External surface values shown are the **closest
current label** — they are not renames (Notion DB options are not renamed tonight;
that rename is follow-up work).

| Canonical state | Filesystem lane | Work Intake DB status | Linear state | auto-dev runner state |
|---|---|---|---|---|
| `captured` | `01-intake` | `inbox` | Backlog | — (pre-run) |
| `triaged` | `01-intake` | `triaged` | Backlog | — (pre-run) |
| `specified` | `02-active` | `spec-ready` | Backlog or Todo | — (pre-run; `--allow-specified` unlocks) |
| `ready` | `02-active` | `queued` | Todo | `discovered` |
| `building` | `02-active` | `in-progress` | In Progress | `implementing` |
| `validating` | `02-active` | `in-progress` | In Review | `pr_open` / `ci_watch` / `copilot_watch` |
| `blocked` | `02-active` | `blocked` | Blocked | `blocked` |
| `finished` | `03-complete` | `done` | Done | `merged` |
| `documented` | `03-complete` | `done` | Done | `merged` |
| `archived` | `03-complete` | `dropped` | Cancelled | `abandoned` |

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
names above in its `states:` list and `lane_state_map:`. The losmon project
already conforms. When adding a new project:

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
  lane_state_map:
    01-intake: [captured, triaged]
    02-active: [specified, ready, building, validating, blocked]
    03-complete: [finished, documented, archived]
```

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
