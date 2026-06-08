# Judgment

Build this as a proposal generator first.

The valuable part of "gets better over time" is not autonomous mutation; it is
the recurring evidence review, clustering, scoring, and handoff into concrete
artifacts. Generated skills, commands, or tools should be draft outputs behind
approval and validation gates until the proposal quality is proven.

After the Hermes-agent review, the direction is stronger:

- Install this as a default shared workflow and disabled-or-dry-run automation,
  because periodic review is what creates the value.
- Copy Hermes' discipline around sidecar telemetry, scoped review prompts,
  per-run reports, and class-level skill/library maintenance.
- Do not copy Hermes' direct mutation posture for v1. Agentic OS should produce
  proposals, draft work packets, and migration plans before any shared skill,
  command, workflow, automation, Notion page, or shell surface changes.
- The Writer/Critic duel passed; use the folded `SPEC.md` as the implementation
  contract.
- Start with P1 only: default-installed templates, schemas, control-plane config,
  and `run --dry-run`. Do not build apply, approval, promotion, or scheduler
  mutation paths until the no-write analyzer and install surface are verified.
