# Investigation

- Prior losmon-memory search for this exact Hermes/self-improvement concept
  returned no hits.
- The repo stores implementation-ready feature work under numbered
  `features/<NN-slug>/` folders with `feature.yml`, `SPEC.md`, and `PLAN.md`.
- The current highest feature prefix is `59`; this local spec uses prefix `60`.
- The atlas says the always-on runtime is now schedulable through
  `agentic-os runtime supervise`, so this feature should hook into that surface
  instead of inventing a second scheduler.
- Existing reference, command, skill, runtime, event graph, and validation
  surfaces give enough structure to make the loop explicit and auditable.
