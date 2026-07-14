# 28 · Doc Config System

> **Purpose:** make document placement predictable across Agentic OS filesystem
> state and the Notion control plane.
>
> **You'll use:** `agentic-os doc-config` for document placement and the
> Spec Engine for tracked software work,
> `harness/shared_factory/00-control-plane/doc-config.yml`, the
> `spec-engine` skill, the `doc-config-router` skill, and
> `harness/rules/os-authoring-rules.md`.
> **Prereqs:** a routed Agentic OS layer and verified Notion workspace before writes.

---

## What It Solves

Agents often receive broad instructions such as "Add this to Notion" or "save this
as the plan." Without a durable routing contract, every agent has to infer where
the content belongs. The Doc Config System makes that inference explicit,
configurable, and testable.

The filesystem remains authoritative. Notion is the human control-plane
projection and must be verified as Genome's Notion or an explicitly selected
client workspace before writes.

## Default Buckets

The default spec/project packet is intentionally small:

| Bucket | Use |
| --- | --- |
| `SPEC` | Raw user language, scope, acceptance criteria, behavior contracts, and out-of-scope boundaries. |
| `PLAN` / `PLANS` | Implementation sequence, dependencies, risks, and validation plan. |
| `WORKLOGS` | Timestamped receipt-backed progress and validation outcomes. Per-work packets still use `WORKLOG.md`. |
| `QUESTIONS` | Created when unresolved questions exist. |

Optional buckets are config-controlled: `DECISIONS`, `ARTIFACTS`, and
`CONVENTIONS`. `Specs` is the parent namespace by default, not a child bucket
inside each spec.

## Search Methods

`doc-config.yml` controls every discovery method, not only grep/ripgrep. Each
method can be toggled on or off:

- `config`
- `markdown`
- `ripgrep`
- `filesystem`
- `notion`
- `context_mode`
- `memory`

Routing plans return enabled methods in priority order so agents can search
without guessing.

## Commands

```bash
agentic-os doc-config doctor --root ~/agentic_os
agentic-os doc-config plan --root ~/agentic_os --request "Add this to Notion" --domain work --project genomes_agentic_os --questions-present
agentic-os doc-config init --root ~/agentic_os --domain work --project genomes_agentic_os
```

Use `/add-spec` for tracked software work. It executes `agentic-os spec add`
through layered `spec_engine` policy. Doc-config may still plan an optional
Notion or filesystem documentation projection, but it no longer owns Spec
lifecycle routing and Notion is not an intake dependency.

Use `/add-bug` for lightweight bug reports, missed enforcement, logging gaps, or
routing drift. Use `/auto-add-spec` when a long Agentic OS request would
otherwise remain only in chat.

Source checkouts used for project work should be visible through the project
`worktrees/` surface. Register external checkouts with
`agentic-os project worktree add` before relying on them for routing or
handoffs.

## Running This From Claude Vs Codex

- **Claude:** use `/add-spec` or the `spec-engine` skill for tracked software
  work; use `doc-config-router` for one-off document placement.
- **Codex:** load the routed `AGENTS.md` context, use `agentic-os spec ...` for
  tracked work, and run `agentic-os doc-config plan` only for document placement.

## Validation

Fresh installs and `docs update` ship:

- active config: `harness/shared_factory/00-control-plane/doc-config.yml`
- template: `harness/shared_factory/05-knowledge/templates/runtime/doc-config.yml`
- schema: `harness/schemas/doc-config.schema.json`
- command doc: `harness/commands/os-doc-config.md`
- intake command doc: `harness/commands/os-add-spec.md`
- legacy intake command doc: `harness/commands/os-new-feature.md`
- bug command doc: `harness/commands/os-add-bug.md`
- auto-spec command doc: `harness/commands/os-auto-add-spec.md`
- legacy auto-feature command doc: `harness/commands/os-auto-add-feature.md`
- skill: `harness/skills/doc-config-router/SKILL.md`
- canonical Spec skill: `harness/skills/spec-engine/SKILL.md`
- legacy intake adapter: `harness/skills/spec-intake-router/SKILL.md`
- legacy intake skill: `harness/skills/feature-intake-router/SKILL.md`
- bug skill: `harness/skills/bug-intake-router/SKILL.md`
- auto-spec skill: `harness/skills/auto-spec-intake/SKILL.md`
- legacy auto-feature skill: `harness/skills/auto-feature-intake/SKILL.md`
- authoring guard skill: `harness/skills/os-authoring-guard/SKILL.md`
- authoring rules: `harness/rules/os-authoring-rules.md`
- compatibility workflow: `harness/shared_factory/04-workflows/spec-intake.md`
- legacy feature adapter: `harness/shared_factory/04-workflows/feature-intake.md`
- legacy bug adapter: `harness/shared_factory/04-workflows/bug-intake.md`

Run:

```bash
agentic-os doc-config doctor --root <root>
agentic-os validate --root <root> --strict
```
