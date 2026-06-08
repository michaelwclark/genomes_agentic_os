# Summary

Feature 60 specifies a local, auditable self-improvement loop that reads durable
memory, conversations, task/workflow/automation evidence, and run logs, then
proposes tools, skills, commands, workflows, checks, or feature specs through
gated artifacts.

The loop should be part of the default installed Agentic OS as a shared workflow
and disabled-or-dry-run automation. Hermes-agent provides useful inspiration for
sidecar telemetry, scoped review prompts, class-level skill maintenance, and
per-run reports, but Agentic OS should generate proposals before mutating shared
surfaces.

The pre-implementation duel passed, and its final spec has been folded into
`SPEC.md`. The v1 loop is now implemented through local files: dry-run, apply,
proposal writes, dedupe/cooldown, approval, rejection, promotion to draft
artifacts, disabled scheduler target, managed-template conflict handling,
validation coverage, and holdout QA.
