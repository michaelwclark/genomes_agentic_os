# 24 · Auto-Dev Readiness

> **Purpose:** decide whether a work item is safe to run through `$auto-dev`,
> understand every blocker the resolver can print, and know which receipts must
> exist before unattended or long-running implementation continues.
>
> **You'll use:** `agentic-os-auto-dev-resolve`, the project `project.yml`
> `dev_factory` block, tracker links, backup restore planning, and the generated
> `artifacts/auto-dev/` receipts.

---

## The Rule

Never start tracker-claiming auto-dev from a hunch. Run the resolver first:

```bash
agentic-os-auto-dev-resolve <project_id> <work_item_number> --root <os_root>
```

If it exits non-zero, do not run `$auto-dev` yet. Fix the printed blocker or move
to a different work item.

---

## Required Starting State

The target work item must be in a build-ready lifecycle state.

| State | Resolver behavior | What to do |
| --- | --- | --- |
| `captured`, `triaged` | Blocked | Groom the item through spec/intake first. |
| `specified` | Blocked by default | Use `--allow-specified` only when the spec is execution-ready and the project policy allows it. |
| `ready`, `building`, `validating`, `blocked` | Allowed to run preflight | Continue only if every preflight check passes. |
| `finished`, `documented`, `archived` | Blocked | Do not reopen through auto-dev without a new work item. |

---

## Preflight Checks

The resolver reads the routed project and the selected work item, then checks:

| Check | Pass condition | Common failure |
| --- | --- | --- |
| `dev_factory` | `project.yml` has `dev_factory.enabled: true`. | Project has not declared tracker, repo, validation, PR, or merge policy. |
| `tracker_link` | The work item has a tracker id in `SPEC.md` frontmatter or an auto-dev tracker snapshot. | Work item was created locally but never projected to the approved tracker. |
| `linear_tracker` | Linear tracker config, workflow states, project, team, and issue are visible to the configured API path. | Wrong team/project id, stale token, missing state, missing issue, or token cannot see the workspace. |
| `repo_path` | `dev_factory.repo.root` exists on the host. | Source repo missing or project config points at the installed root instead of the source repo. |

For Linear-backed projects, a token/team mismatch is a hard blocker. Do not work
around it by manually claiming a tracker. Either fix the approved direct API token
or use a project-approved connector-backed path.

---

## What A Pass Produces

When every gate passes, the resolver writes:

```text
<work-item>/artifacts/auto-dev/run-prompt.md
```

That prompt is the handoff into `$auto-dev`. It includes the resolved project,
work item, tracker id, repository, base branch, validation command, merge policy,
and the receipts that must be produced before closeout.

---

## Receipts To Keep

Every auto-dev run should leave durable evidence, not just chat text.

| Stage | Minimum receipt |
| --- | --- |
| Before large changes | `agentic-os backup run --dry-run` and `agentic-os backup restore-plan` with `coverage.status: covered`. |
| Claim | `artifacts/auto-dev/state.json` plus claim receipt from `auto_dev_state.py`. |
| Local validation | Command output summary and failing-test root cause if any. |
| PR/CI | PR URL, check ids, and watcher artifacts if checks are slow. |
| Finishing review | Review receipt or explicit project policy allowing a skip. |
| Closeout | Worklog update, tracker update, and operator report update if the project has one. |

---

## Common Blocks

### Missing Tracker

Create or sync the intake row first, then copy the tracker id into `SPEC.md`:

```yaml
---
state: ready
tracker: <TEAM>-<NNN>
---
```

### Linear Team Not Visible

The resolver may show `INPUT_ERROR` or "Entity not found: Team". That usually
means the configured Linear ids are correct for one workspace, but the direct API
token belongs to another workspace or lacks access.

Fix the token or use the approved connector-backed provider. Do not bypass the
preflight by treating the tracker as manually claimed.

### Backup Coverage Incomplete

Before a large installed-root change:

```bash
agentic-os backup run --root <os_root> --dry-run
agentic-os backup restore-plan --root <os_root>
```

If restore planning reports `coverage.status: incomplete`, update
`harness/registries/backup-policy.yml` to include the missing critical paths and
run the two commands again.

### Installed Root Validation Has Unrelated Drift

Record the exact validation error and distinguish it from the current work. Do
not mark the slice green if your touched area failed. Do not hide unrelated
pre-existing drift; put it in the worklog as a separate blocker.

---

## Closeout Checklist

- Resolver was run before auto-dev.
- Backup dry-run and restore-plan receipts exist for risky installed-root work.
- Source repo tests passed or a blocker-grade failure was documented.
- Installed-root validation was run, or a specific reason was recorded.
- Source changes were committed and pushed.
- Installed root changes were synced from source or explicitly documented.
- Worklog, tracker, and operator report were updated with receipts.

The goal is not ceremony. The goal is that the next operator can see exactly why
work was safe to start, what changed, what was tested, and what still blocks the
next run.

For tracker ownership, Notion projection, and external-write boundaries, see
[25 · Source Of Truth Rules](25-source-of-truth.md).
