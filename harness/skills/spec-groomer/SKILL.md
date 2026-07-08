---
name: spec-groomer
description: Groom rough software ideas into source-backed implementation specs with original intent, capability discovery, tracker hierarchy, QA, Gherkin, and Notion documentation projection.
---

# Spec Groomer

Use this skill when the user asks to groom a rough idea, product request,
software proposal, OS improvement, or future feature into an implementation-ready
spec.

Do not use this skill to implement the spec. Stop when the packet and requested
projections are ready for the implementation workflow.

## Program Owner

Load `harness/shared_factory/00-programs/spec_grooming/` before changing this
skill, its templates, examples, command surface, projection rules, or registry
entries.

## Core Contract

1. Load the routed Agentic OS layer and active project/work item context.
2. Read `harness/rules/os-authoring-rules.md` when the request changes OS
   commands, skills, workflows, automations, tools, registries, programs,
   templates, or projection rules.
3. Write or update `ORIGINAL_INTENT.md` before polished spec text. Preserve:
   - raw capture;
   - intent anchors;
   - explicit non-goals;
   - assumptions;
   - open questions;
   - iteration deltas.
4. Run doc-config and existing-capability discovery before creating net-new
   work. Search the narrowest useful surfaces first:
   - local work items and program/workflow/automation folders;
   - `harness/`, `docs/`, `templates/`, `src/`, and `.agentic-atlas/` for
     source-package work;
   - Linear/Jira when tracker projection is requested or project config makes it
     cheap;
   - Genome's Notion only after workspace verification when documentation
     projection is requested.
5. Record exactly one route decision in `JUDGMENT.md`:
   `extend_existing`, `create_under_existing`, or `create_new`.
6. Produce a complete packet using the A-plus template:
   - product scope;
   - technical mapping;
   - flow as tables or structured prose;
   - state model;
   - data and artifact model;
   - acceptance criteria;
   - Gherkin scenarios;
   - QA and holdout checks;
   - rollout and backout;
   - projection receipts;
   - assumptions and open questions.
7. Project only sanitized summaries to external trackers. Do not include local
   filesystem paths, private Notion links, secrets, token names, internal run
   paths, or harness-only details in Linear, Jira, GitHub, Slack, or email.
8. Project to Notion only after verifying Genome's Notion. Do not create
   fallback pages in another workspace.

## Route Rules

### LOS Django Or Jira-Primary Work

Delegate to `$jira-product-orchestrator`. Keep the universal packet only as
routing context when useful. The Jira-specific suite owns Jira story/task shape,
ADF rendering, technical mapping, QA, and subtask decomposition.

### Agentic OS Self-Improvement

Use `$aos-product-orchestrator` as the domain adapter when the request is an
Agentic OS self-improvement proposal. This skill may provide the universal
packet quality gate and templates.

### Linear-Primary Or Explicit Linear Requests

Use the configured project profile and available Linear route. Prefer the
unified intake row when that project owns Linear sync; create direct Linear
parent/child issues only when the user explicitly requests real Linear issues or
the project contract requires direct projection.

## Required Packet Files

Minimum groomed packet:

```text
ORIGINAL_INTENT.md
INVESTIGATION.md
JUDGMENT.md
SPEC.md
PLAN.md
HOLDOUT_QA.md
NEXT.md
WORKLOG.md
```

Conditional receipts:

```text
LINEAR.md
JIRA.md
NOTION.md
QUESTIONS.md
```

## Completion Standard

The skill is complete when a fresh implementation agent can open the filesystem
packet and understand:

- the original user request;
- what was searched and reused;
- why the route was selected;
- what to build;
- how to validate it;
- what assumptions remain;
- what tracker or Notion projection happened or was skipped.

