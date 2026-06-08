# Investigation

## Local Context

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

## Hermes-Agent Research

Source inspected: `nousresearch/hermes-agent` at commit
`04bb74c58eff5ac972e31bcf2fa2c7c7aaf5105b`
(`https://github.com/nousresearch/hermes-agent/tree/04bb74c58eff5ac972e31bcf2fa2c7c7aaf5105b`).

Relevant mechanisms:

- `agent/background_review.py` runs a per-turn background review fork. After a
  user turn it replays a conversation snapshot and asks whether memory or skill
  updates should be saved. The fork inherits provider/model/runtime details from
  the parent but is restricted to memory and skills toolsets.
- The background review prompt is active and class-oriented. It prefers updating
  the skill that was just loaded, then an existing umbrella skill, then adding
  `references/`, `templates/`, or `scripts/` support files, and only then
  creating a new class-level skill. It explicitly rejects one-off session
  narratives and transient environment failures as durable skills.
- `agent/curator.py` is the broader maintenance pass. It runs on an interval
  after the first seeded observation, can also be invoked by `hermes curator
  run`, applies pure activity-based transitions, then starts an auxiliary-model
  review over agent-created skills.
- Hermes writes curator state to a sidecar state file and per-run reports under
  `logs/curator/<timestamp>/` with both `run.json` and `REPORT.md`. Reports
  distinguish automatic transitions, LLM tool calls, consolidated skills, pruned
  skills, new skills, and recovery instructions.
- `tools/skill_usage.py` stores operational counters in a sidecar
  `.usage.json`, not in user-authored `SKILL.md`. It tracks use/view/patch
  activity and records provenance so the curator only operates on
  agent-created skills. Counter writes are best-effort and should not break the
  underlying user action.
- `tools/skill_manager_tool.py` treats skills as procedural memory with
  `SKILL.md` plus `references/`, `templates/`, `scripts/`, and `assets/`.
  Hermes can create, patch, write support files, and archive skills directly,
  with guardrails around names, size, provenance, and pinned deletion.
- `cron/scheduler.py` bumps skill usage when scheduled jobs load skills, and
  cron agents skip memory ingestion so scheduled prompts do not pollute user
  memory.
- `cron/jobs.py` rewrites scheduled job skill references after curator
  consolidation or pruning so automations keep loading the correct instructions.

Applicability to Agentic OS:

- Copy the evidence model and report discipline, not Hermes' direct mutation
  posture. Agentic OS should produce proposals and draft artifacts first.
- Treat self-improvement as a default installed workflow plus an optional
  scheduled automation in `harness/shared_factory`, because its value depends on
  regular evidence review.
- Use sidecar telemetry for tool/skill/command/workflow usage, not frontmatter
  churn in authored docs.
- Preserve the class-level target shape: improve existing shared skills,
  commands, workflow templates, and validators before creating narrow new
  artifacts.
- If proposals rename, merge, or retire reusable skills/commands, include an
  automation/workflow reference migration plan so scheduled jobs do not silently
  lose instructions.
