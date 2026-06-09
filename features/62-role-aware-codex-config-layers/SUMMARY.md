# Summary

Feature 62 turns the existing Codex `config.toml` layer system into explicit
role-aware, model-tiered profiles. It preserves current layer placement and
merge safety, but adds navigator/orchestrator/automation-guard identity,
`PROFILE.md`, `config/codex-profile.yml`, compatibility aliases, customer-safe
scan gates, and stronger model defaults for heavy work.

The spec was hardened with the duel workflow and reached PASS in 5 local Codex
rounds.

Implementation is now in place in the source package. Generated layers use
`gpt-5.4-mini` for navigation and routing, `gpt-5.5` for project/workflow/
automation heavy work, write `PROFILE.md` and `config/codex-profile.yml`, and
mirror the role block into `AGENTS.md` for current Codex prompt visibility.
