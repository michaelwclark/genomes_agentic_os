# Pre-Duel Brief: Memory Driven Toolsmith Loop

## Duel Goal

Harden Feature 60 before implementation.

The duel should decide whether the current spec is strong enough to build, and
should identify severe gaps in scope, safety, data contracts, default
installation behavior, workflow/automation integration, and verification.

## Source Packet

Primary files:

- `feature.yml`
- `SPEC.md`
- `PLAN.md`
- `INVESTIGATION.md`
- `JUDGMENT.md`
- `HOLDOUT_QA.md`
- `NEXT.md`

Do not treat implementation as started. This is pre-implementation hardening.

## User Intent To Preserve

The feature should implement a periodic self-improvement loop:

1. Run on a schedule and on demand.
2. Analyze recent logs, conversations, tasks, workflows, automations, tool use,
   validation failures, and durable memories.
3. Detect places where prompts, skills, commands, workflows, automations,
   validation checks, or local tools would save time or reduce repeated errors.
4. Create a new self-improvement proposal or feature/work item when justified.
5. Kick approved proposals through the normal Agentic OS workflow: spec, build,
   test, document, and close out.

Because the loop is valuable only when it runs repeatedly, it should be included
in the default installed Agentic OS as a shared workflow plus a
disabled-or-dry-run schedule target. It should also be present in the current
`~/agentic_os` instance after implementation.

## Hermes-Agent Research To Consider

Inspected upstream source:
`https://github.com/nousresearch/hermes-agent/tree/04bb74c58eff5ac972e31bcf2fa2c7c7aaf5105b`

Relevant Hermes mechanisms:

- Per-turn background review fork in `agent/background_review.py`.
  It replays a conversation snapshot after a turn, asks whether memory or skill
  updates should be written, inherits parent runtime credentials/model, and
  restricts tools to memory and skills.
- Active skill review prompt.
  The prompt prefers patching the skill already loaded in the session, then an
  existing umbrella skill, then support files under `references/`, `templates/`,
  or `scripts/`, and only then a new class-level skill.
- Periodic curator in `agent/curator.py`.
  It runs by interval/manual command, keeps state, applies pure activity-based
  transitions, starts an auxiliary-model review, and writes `run.json` plus
  `REPORT.md`.
- Sidecar skill telemetry in `tools/skill_usage.py`.
  Usage, view, and patch counters live in `.usage.json`, not inside authored
  `SKILL.md` files. Writes are best-effort.
- Skill mutation tooling in `tools/skill_manager_tool.py`.
  Hermes can create, patch, write support files, and archive skills directly.
  Agentic OS should not copy this direct mutation in v1.
- Cron reference migration in `cron/jobs.py`.
  When the curator consolidates/prunes skills, cron job skill references are
  rewritten so scheduled jobs do not silently lose instructions.

## Design Stance

Adopt from Hermes:

- Sidecar telemetry.
- Scoped reviewer tool access.
- Class-level artifact preference over one-session micro-artifacts.
- Per-run machine and human reports.
- Structured distinction between deterministic findings and model proposals.
- Reference migration when reusable artifacts change.

Depart from Hermes:

- No direct mutation of shared skills, commands, workflows, automations, Notion,
  shell config, or global harness surfaces in v1.
- The first implementation should write proposals and draft artifacts only.
- Operator approval and validation are required before promotion.

## Questions For The Duel

- Is Feature 60 now scoped as a default OS workflow and automation clearly enough
  to implement without inventing new runtime surfaces?
- Are the evidence inputs and sidecar telemetry contract specific enough?
- Are proposal schemas strong enough to prevent vague "improve prompts" notes?
- Are the safety rules sufficient for prompt injection, secrets, and accidental
  self-modification?
- Does promotion need one path or multiple explicit subcommands?
- What is the smallest useful v1 slice that still proves the loop end to end?
- What tests would catch the most likely false-positive and unsafe-write bugs?

## Expected Duel Output

The duel should produce a hardened spec. If it returns PASS, use the final spec
as input to implementation. If it returns non-PASS, fold the severe issues back
into the feature markdowns before implementation starts.
