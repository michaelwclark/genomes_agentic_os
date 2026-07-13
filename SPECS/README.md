# Specs

Source-package future-work specs and the planning backlog live here. The
legacy `PLANS/` directory has been consolidated into this folder; numbered
plan files keep their numbers.

On install or `docs update`, these files are copied into the installed
runtime at:

```text
<os-root>/harness/shared_factory/05-knowledge/plans/
```

The installed copy path is unchanged from the legacy layout so existing
installs keep updating additively. It gives future agents a durable place to
find what should be built next without searching chat history.

## Status Vocabulary

- `draft`: direction is captured, but implementation details need review.
- `ready`: enough detail exists for an agent to implement.
- `building`: active implementation is underway.
- `validating`: implementation exists and needs real usage evidence.
- `done`: shipped, installed, validated, and documented.

## Writing Rule

Every spec should name concrete files, commands, state changes, and
validation. If a spec cannot be tested from a fresh install, it is not
specific enough yet.
