# Judgment

## Decision

Consolidate the user's request into one OS feature: project work lifecycle plus
conversation auto logging.

This should be a numbered source plan because it changes the product contract of
the installed OS. It also gets a source feature packet because implementation
work needs feature-60-style state tracking.

## Placement

- Source backlog: `PLANS/22-project-work-lifecycle-and-conversation-auto-logging.md`
- Source feature packet:
  `features/61-project-work-lifecycle-and-conversation-auto-logging/`
- Installed runtime after docs update:
  `harness/shared_factory/05-knowledge/plans/22-project-work-lifecycle-and-conversation-auto-logging.md`

## Rationale

Putting this only under installed `shared_factory/05-knowledge/plans/future-ideas`
would make it a local idea. The requested behavior belongs in the reusable source
package so every future project and customer OS can inherit it.

## Naming Decision

Conversation logs should use `YYYY_MM_DD_<slug>` rather than `MM_DD_YYYY_<slug>`
so names sort chronologically and avoid date ambiguity.

## Safety Decision

The auto logger must be non-blocking, redacted, and project-policy controlled.
Raw transcript persistence can be disabled per project or customer profile.
