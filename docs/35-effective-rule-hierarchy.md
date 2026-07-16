# 35 · Effective Rule Hierarchy

> **Purpose:** give agents and Command Center one deterministic answer to
> “which rules apply here?” without copying, concatenating, or trusting arbitrary
> Markdown paths.

## Effective order

The projection understands `system`, `os`, `domain`, `project`, `workflow`, and
`automation` scopes. A rule is grouped with definitions that share its `key`
(the rule `id` is the default key). Resolution is intentionally conservative:

1. Higher `strictness` wins.
2. At equal strictness, the more restrictive effect wins:
   `deny` → `require` → `prefer` → `allow` → `inform`.
3. At equal strictness and effect, the narrower scope wins.
4. A stable qualified ID breaks a remaining tie.

This means a broad safety prohibition cannot be weakened by a narrower allow.
A project may refine a system rule when it is equally strict or stricter. Every
shadowed definition remains in the result with the winning ID and reason.

## Source boundary

The engine uses the context-contract resolver for `RULES.md` inheritance. Its
`context_parity.rule_source_refs` field is the ordered list returned by that
resolver. Only those files are rendered.

Structured definitions come from canonical registry paths derived from the
selected target:

- `harness/registries/rules.yml`
- `<domain>/00-control-plane/resource-registries/rules.yml`
- `<domain>/02-projects/<project>/config/resource-registries/rules.yml`

The registry `source` field is provenance metadata. The query engine never
opens it, so a malformed, absolute, or traversal-like source cannot make the UI
render an arbitrary file. Markdown displayed for a structured rule comes only
from its registry `body_markdown`, summary, or description.

## Projection contract

`rules/v1` returns stable qualified IDs, scope-specific display numbers such as
`SYS-001` and `PRJ-003`, one-sentence summaries, Markdown bodies, safe
references, effect/strictness, local/inherited state, hashes, modified time,
validation, conflict evidence, and aggregate counts. Source references are
always relative to the selected OS root.

Malformed optional registries produce `partial_rule_registry` warnings while
the remaining projection stays available. Same-key semantic duplicates produce
`duplicate_rule`; incompatible definitions produce `rule_conflict` with exact
IDs and source references.

## Operator commands

```bash
agentic-os rules effective --root ~/agentic_os

agentic-os rules effective \
  --domain los --project los_app_los_django \
  --scope project --effect deny --json \
  --root ~/agentic_os

agentic-os rules effective \
  --domain shared_factory --lane engineering \
  --automation closed_worktree_cleanup \
  --conflicts-only --root ~/agentic_os
```

Use `--query` to search IDs, keys, names, summaries, and source references.
`--local-only` isolates definitions declared at the selected target scope.
Repeat `--scope` or `--effect` for multi-value filters. YAML is the human
default; `--json` is the GUI/API form.

## Running this from Claude vs Codex

Claude and Codex call the same CLI and receive the same `rules/v1` projection.
Provider or model selection does not alter rule precedence. Harness-specific
presentation belongs in the client, not in the effective-rule engine.
