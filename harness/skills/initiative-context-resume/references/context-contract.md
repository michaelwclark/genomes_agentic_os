# Initiative Context Contract

## Purpose

Long-running initiatives need a small, durable context layer that survives chat compaction, agent handoff, Notion drift, and Jira creation later. The context pack is not a full spec. It is the navigation layer that tells the next agent what to load and what not to re-derive.

## Required Convention

For project-backed initiatives, use this shape:

```text
<domain>/02-projects/<project>/
  status.md
  source-map.md
  work-items/
    <date>-<nnn_slug>/
        CONTEXT.md
        work.yml
        SPEC.md
        PLAN.md
        DECISIONS.md
        QUESTIONS.md
        NEXT.md
        WORKLOG.md
```

Use status `captured` while the initiative is unbuilt spec/planning work. Change
the lifecycle state in metadata without moving the packet.

## Required CONTEXT.md Sections

Each initiative context pack must include:

- Identity: title, domain, project, lane, status, current phase, updated timestamp.
- Summary: the current one-paragraph understanding of the initiative.
- Resume load order: exact files, docs, artifacts, and source pages to read first.
- Source of truth: authoritative planning/spec/docs links and package paths.
- Decisions: stable decisions already made, with dates when useful.
- Code anchors: known repo modules, models, tasks, settings, or workflows the design must respect.
- Open questions: blockers or assumptions that still need validation.
- Next actions: concrete actions for the next agent/human.
- External-output boundary: what must stay out of Jira/GitHub/Slack/email.
- Staleness rule: when to refresh Notion, docs, code anchors, or generated design packages.

## Required Index Updates

The context pack is not complete until all relevant discovery surfaces point to it:

- Project `status.md`: current status, path, next action, and last update.
- Project `source-map.md`: source-of-truth docs, artifacts, and code anchors.
- Domain `00-control-plane/active-work.md`: active/captured initiative pointer when available.
- Project memory: durable rule or note when the context matters across future sessions.

Use managed marker blocks for generated entries:

```text
<!-- initiative-context-resume:<surface>:<slug>:start -->
...
<!-- initiative-context-resume:<surface>:<slug>:end -->
```

This keeps reruns idempotent and lets humans edit normal prose around generated entries.

## Quality Bar

A context pack is good enough when a future agent can answer these questions in under five minutes:

- What is this initiative and why does it exist?
- What exact docs/artifacts should I load first?
- What has already been decided?
- Where does it integrate with the existing code/workflow?
- What is the next useful action?
- What information is private or external-output unsafe?

## Anti-Patterns

- A Notion link with no local summary.
- A local artifact path with no explanation of why it matters.
- A work item with `NEXT.md` but no source-of-truth links.
- Duplicate planning documents that disagree without a stated canonical source.
- Jira-ready decomposition before the source-of-truth design is stable.
