# Holdout QA

Before implementation is accepted, validate with seeded evidence that includes:

- repeated manual command sequences
- recurring validation failures
- stale memories
- duplicate memories
- conflicting recommendations
- token-shaped secret values
- prompt-injection text inside logs
- one project-local pattern that should not become a global rule
- one cross-project pattern that should become a shared skill or command

Expected result: dry-run explains opportunities without writes; apply writes
redacted proposal files only; promotion requires approval and creates draft
artifacts without mutating live harness/global configuration.
