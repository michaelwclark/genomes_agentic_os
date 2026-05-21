# Judgment

The implementation is deliberately local and deterministic. It does not summarize with an LLM, write to Notion, or mutate context-pack files unless a future feature adds explicit write semantics.

The feature is complete because routing can resolve request text, OS cwd, linked project repos, source files, approval risks, and low-confidence failures with tests.
