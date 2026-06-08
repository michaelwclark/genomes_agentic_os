# Memory

- 2026-05-30: Feature 60 captures the memory-driven toolsmith loop as an
  explicit scheduled analyzer over durable evidence. The first implementation
  should write reviewable proposals, not mutate live harness or Notion surfaces.
- 2026-05-31: Hermes-agent research showed two useful patterns for this feature:
  per-turn background memory/skill review and periodic curator-style library
  maintenance with sidecar telemetry and reports. Agentic OS should adapt those
  patterns as default installed workflow/automation surfaces, but keep v1
  proposal-only until operator approval and validation.
- 2026-05-31: Pre-implementation duel passed using local Codex CLI for both
  writer and critic after the default Claude writer failed for local account
  credit. The PASS final spec is
  `.duels/2026-05-31-codex-local/final-spec.md`; fold it into the main feature
  files before implementation.
- 2026-06-03: Folded the PASS duel artifact into `SPEC.md` and aligned
  `PLAN.md`, `HOLDOUT_QA.md`, `NEXT.md`, and `JUDGMENT.md` for implementation.
  P1 is the first build slice: managed templates, schemas, default install
  surface, and `self-improvement run --dry-run` only.
- 2026-06-08: Completed v1 implementation. `agentic-os self-improvement`
  supports dry-run, apply, status, list, show, approve, reject, and promote.
  Apply writes only local run/proposal records; approval is content-bound;
  promotion writes draft artifacts only; runtime scheduling includes a disabled
  dry-run target. Verification passed with 97 tests and temp-root smoke.
