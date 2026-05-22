# Investigation

Feature 00 established the initial plan backlog and runtime plan mirror. It did
not add a dedicated CLI command. The affected command surfaces are:

- `agentic-os init --target <root>`
- `agentic-os docs install --root <root>`
- `agentic-os docs update --root <root>`
- `agentic-os validate --root <root>`

Affected source paths:

- `PLANS/README.md`
- `PLANS/00-current-state-and-gap-map.md`
- `PLANS/09-future-ideas-intake.md`
- `features/00-current-state-and-gap-map/`

Expected generated runtime paths:

- `<root>/shared_factory/05-knowledge/plans/README.md`
- `<root>/shared_factory/05-knowledge/plans/00-current-state-and-gap-map.md`
- `<root>/shared_factory/05-knowledge/plans/09-future-ideas-intake.md`

Expected failure modes:

- Missing docs install/update leaves runtime plan files absent.
- Stale runtime files can remain if the operator edits runtime copies instead
  of updating source.
- Structural validation can pass while a specific plan file is stale because
  validation checks required structure and parseability, not semantic freshness.

