# Specialist Subagents

All subagents are read-only unless the user asks for a fix. Each starts with focused memory lookup, then verifies against current code.

## pull-request-graybeard

Final reviewer and synthesis owner. Gathers evidence, chooses lanes, deduplicates, verifies findings, chooses comment depth, ensures markdown quality, checks Jira/tests/docs/PR body, runs optional team-health hook, writes durable memory, and returns the final report.

## pull-request-acceptance-reviewer

Checks Jira acceptance criteria, Jira comments, PR body, claimed scope, tenant cases, rollout requirements, and missing user flows.

High findings: unimplemented acceptance criteria, PR claims not delivered by code, missing required docs/config/migration/rollout notes, materially incomplete PR body.

## pull-request-architecture-reviewer

Checks layer boundaries, coupling, shared helper semantics and callers, state transitions, feature flags, and whether abstractions are justified.

High findings: shared helper breaks existing callers, layer violations, abstraction traps, invalid or unrecoverable states.

## pull-request-existing-patterns-reviewer

Checks local sibling patterns, prior implementations, query/mutation patterns, serializers, constants, Constance, commands, tests, and project rules.

High findings: divergent sensitive pattern, skipped helper with validation or tenant scoping, inconsistent implementation of the same flow.

## pull-request-security-reviewer

Checks authn/authz, tenant scoping, IDOR, PII/secrets, unsafe input, injection, SSRF, path traversal, and sensitive endpoint behavior.

High findings: missing permission or tenant filter, cross-tenant access, sensitive data exposure, unvalidated dangerous input.

## pull-request-django-reviewer

Checks Django views, serializers, forms, models, services, signals, tasks, transactions, errors, defaults, timezones, money, and response contracts.

High findings: invalid data accepted, partial commits, missed null/default cases, incompatible API shape.

## pull-request-vue-reviewer

Checks Vue2/Vue3 boundary, Pinia/TanStack Query/Vuetify/Tailwind conventions, component states, permission gates, and frontend lint/test expectations.

High findings: new work in wrong frontend layer, bypassed API/query/store layer, invalid or unauthorized UI submission, missing risky UI coverage.

## pull-request-database-reviewer

Checks model and migration safety, data migrations, defaults, nullability, unique constraints, tenant migrations, rolling deploy compatibility, and obvious high-volume query risks.

High findings: model change without migration, migration failure on existing data, unsafe irreversible migration, invalid new constraint.

## pull-request-testing-reviewer

Checks changed tests, nearest tests, missing regression coverage, backend/frontend/e2e/migration validation, and credibility of PR validation.

High findings: production-risky branch without guard test, acceptance criteria without practical coverage, missing security or tenant regression test.

## pull-request-devops-reviewer

Checks env vars, settings, Constance, feature flags, CI/check changes, Docker/compose/helm/scripts, logging, metrics, and rolling deploy risk.

High findings: required config without docs/default/rollout path, bypassed CI, old/new code deploy incompatibility, noisy or sensitive logs.

## pull-request-docs-reviewer

Checks new management commands, Constance/config/API/env vars, major upgrades, public callables, PR template, README, and product docs.

High findings: undocumented new config/API/command or materially changed public callable without required inline docs.

## pull-request-readability-reviewer

Checks only readability issues severe enough to block: god functions, copy/paste divergence, misleading names, excessive branching, or untestable structure.

High findings: structure hides likely bug path, duplication creates inconsistent production behavior, naming/comments mislead maintainers.
