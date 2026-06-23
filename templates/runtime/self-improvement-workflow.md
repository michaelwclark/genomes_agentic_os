# Self-Improvement Review

Use this workflow to turn repeated local operating friction into deterministic
repairs, morning reports, and reviewable draft work.

## Default Posture

- Scheduled execution is disabled unless the operator changes
  `00-control-plane/self-improvement.yml`.
- Dry-run writes nothing.
- Morning apply may fix deterministic validation drift and publish the morning
  report. Proposal approval and promotion still require later safety gates.

## Review Loop

1. Load the self-improvement control plane.
2. Collect bounded local evidence from allowlisted roots.
3. Redact secret-shaped values before reporting or model review.
4. Repair deterministic validation drift that has an allowlisted fix path:
   missing required files/folders and invalid JSON placeholders with backups.
5. Derive deterministic findings from repeated failures, manual workflows,
   stale sidecars, missing templates, and cooldown state.
6. Keep model review disabled unless a no-tool sandbox is available.
7. Emit a filesystem report and, after Genome's Notion workspace verification,
   a Notion report page with a logs subpage.

## Promotion Rule

Generated improvements beyond deterministic doctor-fix must become proposals or
draft work packets first. Do not mutate live skills, commands, workflows,
automations, shell config, or harness globals from proposal review alone.
