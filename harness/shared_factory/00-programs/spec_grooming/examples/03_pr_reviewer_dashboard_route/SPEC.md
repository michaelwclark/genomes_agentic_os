# Spec: PR Reviewer Dashboard Route

## Problem

Dashboard requests can create duplicate attention surfaces when a workflow or
automation already owns the same operational question.

## Outcome

The groomer routes PR dashboard ideas through discovery first and selects the
existing PR-health owner when evidence supports it.

## Existing Capability Discovery

| Surface | Evidence | Decision |
| --- | --- | --- |
| Team PR board | Existing grouped PR-health projection and merged-row handling. | Candidate owner. |
| Active PR board | Existing personal active PR surface. | Candidate owner for personal PRs. |
| PR cross-review | Existing harness cross-review command. | Related execution surface. |

## Route Decision

- Decision: `extend_existing`
- Owner surface: current PR health or team PR sync surface, depending on
  project scope.
- Rationale: the request is a projection improvement, not a net-new dashboard.

## Technical Plan

| Area | Change |
| --- | --- |
| Discovery | Search PR health and active PR surfaces before creating dashboard work. |
| Packet | Record selected owner and rejected duplicate dashboard route. |
| Projection | Point implementation subtasks at the existing owner surface. |

## Flow

| Step | Input | Output |
| --- | --- | --- |
| Capture | Dashboard idea | Raw intent anchors |
| Discover | Existing PR board/workflow docs | Candidate owner |
| Decide | Owner evidence | `extend_existing` |
| Groom | Enhancement spec | Implementation-ready packet |

## State Model

| State | Meaning |
| --- | --- |
| idea_captured | Dashboard request is preserved. |
| owners_found | Existing PR surfaces identified. |
| route_selected | Enhancement target chosen. |
| ready | Enhancement packet ready for implementation. |

## Acceptance Criteria

- Discovery mentions existing PR board or PR health surfaces.
- Route decision records why a new dashboard is not created.
- Gherkin and QA cover duplicate-surface prevention.

## Gherkin

```gherkin
Feature: PR dashboard grooming
  Scenario: Existing PR surface found
    Given a user asks for a PR reviewer dashboard
    When the groomer finds a matching PR health surface
    Then the route decision is extend_existing
    And the packet does not create a parallel dashboard owner
```

## QA Plan

| Risk | Test |
| --- | --- |
| Duplicate dashboard | Search existing PR surfaces and verify route decision. |
| Scope confusion | Separate team-wide and personal PR dashboard owners. |
| Projection leak | Keep internal OS paths out of external issue descriptions. |

## Projection

Linear projection should create an enhancement under the existing PR health
owner. Notion projection should update the existing product page instead of
creating a second dashboard page.

