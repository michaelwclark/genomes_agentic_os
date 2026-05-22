# Investigation

Feature 11 already provides the room-first profile installation path through
`agentic-os init --profile`, profile validation through
`agentic-os profile validate`, and installed root validation through
`agentic-os validate --root`.

The holdout checks the shipped CLI surface rather than internal helpers:

- `uv run --extra dev pytest -q`
- `uv run agentic-os profile validate <profile>`
- `uv run agentic-os init --target <temp-root> --profile <profile>`
- `uv run agentic-os validate --root <temp-root>`

The smoke profile declares two rooms: `writing_room` and `operations_room`.
It uses the implemented profile shape for `tools`, where each tool is a
mapping with `name`, `trigger`, and `notes`.
