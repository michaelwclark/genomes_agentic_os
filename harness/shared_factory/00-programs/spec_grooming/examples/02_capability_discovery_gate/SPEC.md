# Spec: Capability Discovery Gate

## Problem

Agents can create parallel work when a related program, workflow, automation, or
tracker item already exists. The user then gets multiple half-overlapping
surfaces instead of one strengthened owner.

## Outcome

Add a required discovery gate to `spec-groomer`. Every groomed packet records
search evidence, a route decision, and the reason duplicate owner surfaces were
not created.

## Existing Capability Discovery

| Surface | Evidence | Decision |
| --- | --- | --- |
| Local work items | Search active, intake, and complete lanes for matching terms. | Required before net-new packet. |
| Source docs | Search `harness/`, `docs/`, `templates/`, and `.agentic-atlas/`. | Required for OS-level work. |
| Tracker | Search Linear/Jira when projection is requested or configured. | Required before creating parent tasks. |
| Notion | Search Genome's Notion when documentation projection is requested. | Required after workspace verification. |

## Route Decision

- Decision: `extend_existing`
- Owner surface: the matching program/workflow/skill/tracker item found by
  discovery.
- Rationale: the groomer should strengthen an existing owner whenever one
  already represents the request.

## Technical Plan

| Area | Change |
| --- | --- |
| Skill | Add discovery checklist before packet polish. |
| Template | Require discovery table and route decision. |
| QA | Add holdout that fails if `JUDGMENT.md` is missing. |

## Flow

| Step | Actor | Output |
| --- | --- | --- |
| Search local surfaces | Groomer | Candidate owner list |
| Search live surfaces when needed | Groomer | Tracker/doc evidence |
| Score overlap | Groomer | Selected route |
| Record judgment | Groomer | `JUDGMENT.md` |

## State Model

| State | Meaning |
| --- | --- |
| discovery_not_started | No owner evidence exists. |
| discovery_running | Searches are underway. |
| discovery_recorded | Evidence table exists. |
| route_selected | One route decision is recorded. |

## Acceptance Criteria

- Every groomed packet includes discovery evidence.
- Every groomed packet includes one route decision.
- New owner surfaces require a "why not extend" explanation.

## Gherkin

```gherkin
Feature: Capability discovery gate
  Scenario: Existing owner found
    Given a rough idea overlaps an existing OSProgram
    When spec-groomer runs discovery
    Then the packet records extend_existing
    And no parallel OSProgram is created
```

## QA Plan

| Risk | Test |
| --- | --- |
| Weak search | Use terms from the raw request and synonyms from existing docs. |
| Hidden assumptions | Require assumptions and open questions in packet output. |
| Duplicate owner | Fail holdout if discovery does not mention the matching surface. |

## Projection

Linear or Notion projection should include the route decision summary, not raw
private discovery paths.

