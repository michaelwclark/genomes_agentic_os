# Investigation

Feature 14 is validated through runtime command and skill installation under
`shared_factory/05-knowledge/`.

The holdout uses:

- `uv run --extra dev pytest -q`
- `uv run agentic-os init --target <temp-root>`
- `uv run agentic-os docs update --root <temp-root>`
- `uv run agentic-os validate --root <temp-root>`

The smoke removes one managed command to test restoration and removes another
required command after validation to confirm the validator catches missing
playbook surfaces.
