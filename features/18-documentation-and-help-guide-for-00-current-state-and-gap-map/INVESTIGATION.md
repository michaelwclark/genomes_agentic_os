# Investigation

Feature 00 created the backlog and runtime plan mirror contract. The relevant
source artifacts are:

- `PLANS/00-current-state-and-gap-map.md`
- `PLANS/README.md`
- `features/00-current-state-and-gap-map/`
- `BUILD_LOGS/*.md`

The source feature did not introduce a standalone CLI command. Its operational
surface is the docs install/update path plus validation:

- `agentic-os docs install --root <root>`
- `agentic-os docs update --root <root>`
- `agentic-os validate --root <root>`

The new guide belongs under `docs/13-feature-guides/` because it documents a
completed feature rather than changing the core operating model.

