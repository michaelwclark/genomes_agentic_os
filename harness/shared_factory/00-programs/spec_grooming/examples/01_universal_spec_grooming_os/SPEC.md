# Spec: Universal Spec Grooming OS

## Problem

The OS has intake and domain groomers, but rough ideas can still fragment across
idea, spec, program, workflow, automation, Linear, Jira, and Notion surfaces.
Agents can create duplicate owner surfaces and can polish away the user's
original request.

## Outcome

Add `spec_grooming` as the shared OSProgram and `spec-groomer` as the universal
entry skill. The groomer captures intent, discovers existing capability, records
a route decision, writes an implementation-grade packet, and projects sanitized
receipts to tracker and Notion surfaces when requested.

## Existing Capability Discovery

| Surface | Evidence | Decision |
| --- | --- | --- |
| `jira-product-orchestrator` | Strong Jira-specific suite for stories, subtasks, QA, and Jira formatting. | Keep as LOS/Jira adapter. |
| `aos-product-orchestrator` | Already handles Agentic OS product shaping and intake projection. | Reuse as AOS adapter. |
| `spec-intake-router` | Owns doc-config and filesystem packet placement. | Reuse for packet routing. |
| `program-builder` | Owns OSProgram creation and docs. | Use for program structure. |

## Route Decision

- Decision: `create_under_existing`
- Owner surface: `harness/shared_factory/00-programs/spec_grooming/`
- Rationale: the missing capability is a universal wrapper and quality
  contract, not a replacement for specialized groomers.

## Technical Plan

| Area | Change |
| --- | --- |
| Program | Add OSProgram docs and component map. |
| Skill | Add `spec-groomer` procedure and guardrails. |
| Command | Add `/groom-spec` command contract. |
| Templates | Add original intent and A-plus spec packet templates. |
| Registries | Register skill and command in generated and source registries. |
| Install | Copy source `harness/shared_factory` program assets during docs install/update. |

## Flow

| Step | Input | Output |
| --- | --- | --- |
| Capture | Rough request | `ORIGINAL_INTENT.md` |
| Discover | Local and live surfaces | `INVESTIGATION.md` |
| Decide | Discovery evidence | `JUDGMENT.md` |
| Groom | Route decision and templates | `SPEC.md`, `PLAN.md`, `HOLDOUT_QA.md` |
| Project | Verified tracker and Notion targets | `LINEAR.md`, `NOTION.md` receipts |

## State Model

| State | Meaning |
| --- | --- |
| raw_captured | Original request and anchors are recorded. |
| discovery_running | Existing capability search is in progress. |
| route_selected | One of the three route decisions is recorded. |
| packet_groomed | Product, technical, QA, rollout, and acceptance sections exist. |
| projected | Optional Linear/Jira/Notion receipts are recorded. |
| ready_for_implementation | Packet has enough detail for build orchestration. |

## Acceptance Criteria

- `spec_grooming` is listed as a shared OSProgram.
- `spec-groomer` is registered as a shared skill.
- `/groom-spec` is registered as a command.
- LOS/Jira requests delegate to `$jira-product-orchestrator`.
- Templates preserve raw intent and require assumptions/open questions.
- Example packets cover product, technical, Gherkin, QA, routing, and projection.

## Gherkin

```gherkin
Feature: Universal spec grooming
  Scenario: Preserve original intent
    Given a user submits a rough idea
    When the groomer creates a packet
    Then ORIGINAL_INTENT.md contains the raw capture and anchors
    And assumptions are not written as confirmed facts
```

## QA Plan

| Risk | Test |
| --- | --- |
| Duplicate owner surface | Verify discovery and route decision exist before SPEC.md. |
| Jira route regression | Submit LOS/Jira request and verify delegation text. |
| Projection leak | Scrub tracker drafts for local paths and private Notion links. |

## Projection

- Linear: parent `CC-188` with child issues `CC-189` through `CC-192`.
- Notion: Genome's Notion product report after workspace verification.

