# Self-Improvement Review

Use this workflow to turn repeated local operating friction into reviewable
draft work, not live mutation.

## Default Posture

- Scheduled execution is disabled unless the operator changes
  `00-control-plane/self-improvement.yml`.
- Dry-run writes nothing.
- Apply, approval, and promotion require later safety gates.

## Review Loop

1. Load the self-improvement control plane.
2. Collect bounded local evidence from allowlisted roots.
3. Redact secret-shaped values before reporting or model review.
4. Derive deterministic findings from repeated failures, manual workflows,
   stale sidecars, missing templates, and cooldown state.
5. Keep model review disabled unless a no-tool sandbox is available.
6. Emit a dry-run report for the operator.

## Promotion Rule

Generated improvements must become proposals or draft work packets first. Do
not mutate live skills, commands, workflows, automations, Notion, shell config,
or harness globals from the review step.
