# Feature Spec: Future Ideas Intake

## Status

- Status: ready
- Owner: Genome
- Created: 2026-05-20
- Target OS layer: source package and installed runtime

## Problem

Future ideas currently risk living in chat, repo notes, or scattered project files. The source package needs a `PLANS/` backlog, and installed OS roots need the same durable place for future OS ideas and customer patterns.

## Outcome

Ideas and future plans have a clear routing rule:

- Reusable OS product work goes in `PLANS/` in this repo.
- Installed runtime copies live at `shared_factory/05-knowledge/plans/`.
- Domain-specific ideas go to `<domain>/01-inbox/raw-ideas.md` until triaged.
- Customer-specific work goes to that customer's domain or project, with reusable patterns linked back to shared plans.

## Installed Runtime Location

```text
~/agentic_os/shared_factory/05-knowledge/plans/
```

## Source Templates

```text
templates/planning/feature-spec.md
templates/planning/future-idea.md
```

## Harness Command

```text
shared_factory/05-knowledge/commands/os-capture-plan.md
```

## Required Side Effects

- `agentic-os init` installs the plan directory.
- `agentic-os docs update` adds missing plan files without overwriting existing installed copies.
- Validation checks that the installed plan index exists.
- Future agents are told to put OS feature specs here instead of leaving them in chat.

## Out Of Scope

- Automatic prioritization.
- Notion task creation.
- Customer-facing publication.

## Acceptance Criteria

- Source repo has a `PLANS/` directory with numbered specs.
- Installed OS gets `shared_factory/05-knowledge/plans/`.
- Templates exist for future specs and loose ideas.
- `os-capture-plan.md` tells agents where to put new plans.
- Tests verify plans are installed and additive updates preserve local edits.

## Validation

- `pytest -q`
- `agentic-os docs update --root ~/agentic_os`
- `agentic-os validate --root ~/agentic_os`
