# OS Self-Improvement

Run local Agentic OS self-improvement reviews, deterministic morning repairs,
and filesystem/Notion reports.

## Dry Run

```bash
agentic-os self-improvement run --root ~/agentic_os --dry-run
```

Dry-run reads bounded evidence from allowlisted roots, redacts secret-shaped
values, derives deterministic findings, and prints a report. It writes no run
records, proposals, approvals, drafts, Notion pages, skills, commands,
workflows, automations, shell config, or harness globals.

## Morning Report

```bash
agentic-os self-improvement morning-report --root ~/agentic_os --dry-run
agentic-os self-improvement morning-report --root ~/agentic_os --apply
```

The morning report runs a bounded deterministic doctor-fix pass, then runs the
self-improvement evidence review. Apply mode writes:

- generated repair artifacts only for deterministic validation drift, such as
  missing required files/folders and invalid JSON placeholders with backups,
- a dated filesystem report and logs under
  `harness/shared_factory/06-runs-and-logs/self-improvement/morning-reports/`,
- a Notion page under `Genome's Agentic OS / Self Improvement Reports`, with a
  subpage for the day's logs, after direct API workspace verification.

Set `notion_report.parent_page_id` in
`harness/shared_factory/00-control-plane/self-improvement.yml` when the Notion
integration can write to a known page but `/search` cannot discover it.

`--no-fix` writes the report without applying deterministic repairs.
`--no-notion` skips page projection and keeps the filesystem report as the only
output surface.

## Proposal Lifecycle

```bash
agentic-os self-improvement run --root ~/agentic_os --apply
agentic-os self-improvement status --root ~/agentic_os
agentic-os self-improvement list --root ~/agentic_os
agentic-os self-improvement show <proposal_id> --root ~/agentic_os
agentic-os self-improvement approve <proposal_id> --target feature-spec --root ~/agentic_os
agentic-os self-improvement reject <proposal_id> --root ~/agentic_os
agentic-os self-improvement promote <proposal_id> --target feature-spec --root ~/agentic_os
```

Apply writes run records and proposal files only under
`harness/shared_factory/06-runs-and-logs/self-improvement/`. Promotion creates
draft artifacts only; it does not install generated skills, commands, workflows,
automations, validators, or Notion pages.
