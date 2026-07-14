# 10 Notion Control Plane Bootstrap

## Table Of Contents

- [Purpose](#purpose)
- [Commands](#commands)
- [Bootstrap Plan Contents](#bootstrap-plan-contents)
- [Apply Guardrails](#apply-guardrails)
- [Local Manifest](#local-manifest)
- [Source Artifacts](#source-artifacts)

## Purpose

Feature 10 creates a guarded bootstrap plan for the Agentic OS Notion control
plane. It defines the home page, MVP databases, dashboard views, recent run
seeds, and local manifest state without making Notion the runtime database.

## Commands

Preview the bootstrap plan:

```bash
agentic-os notion bootstrap --root ~/agentic_os --dry-run
```

Apply after verifying workspace and parent page:

```bash
agentic-os notion bootstrap --root ~/agentic_os \
  --apply \
  --verified-workspace "Genome's Notion" \
  --parent-page-id <page_id>
```

## Bootstrap Plan Contents

The plan includes:

- `Agentic OS` home page
- MVP databases for inbox, work items, runs, approvals, and domains
- dashboard views such as Needs Approval, Active Work, Waiting On Me, Running
  Or Failed Runs, Recent Outputs, Automation Health, Inbox To Triage, and
  Decisions This Week
- recent run seeds from installed runtime run logs

## Apply Guardrails

Apply requires both `--verified-workspace "Genome's Notion"` and
`--parent-page-id <page_id>`.

Blocked personal Notion workspaces are refused. A wrong workspace is refused.
This preserves Genome's Notion as the intended control-plane destination.

## Local Manifest

Apply writes:

```text
.notion-control-plane/manifest.yml
```

The manifest is local source-of-truth mapping state for the planned control
plane. Review it before treating any remote Notion surface as current.

## Source Artifacts

- Historical Spec: migrated into the installed project's canonical `work-items/` lifecycle.
- Installed worklog spec: `worklogs/source-features/10-notion-control-plane-bootstrap/SPEC.md`
- Installed worklog QA: `worklogs/source-features/10-notion-control-plane-bootstrap/HOLDOUT_QA.md`
- Implementation: `src/genomes_agentic_os/notion_sync.py`
- CLI wiring: `src/genomes_agentic_os/cli.py`
- Test coverage: `tests/test_cli_scaffold.py`
