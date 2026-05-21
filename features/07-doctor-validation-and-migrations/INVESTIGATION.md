# Investigation

- Existing `validate_root` covers structure but not stale run state, active work, workflow readiness, or automation maturity.
- `init_os` and `install_docs` already preserve existing files, so they are safe repair primitives for source-owner roots.
- Migration apply needs a saved preview hash to detect target drift between review and apply.
