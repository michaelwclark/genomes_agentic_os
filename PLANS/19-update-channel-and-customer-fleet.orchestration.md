# Plan 19 Orchestration Prompt

Use this prompt to start the Plan 19 orchestration run after the installed OS has visible capability registries and a stable validation story.

## Source Spec

- Spec: `/Users/genome/projects/genomes_agentic_os/PLANS/19-update-channel-and-customer-fleet.md`
- Companion prompt: `/Users/genome/projects/genomes_agentic_os/PLANS/19-update-channel-and-customer-fleet.orchestration.md`
- Supporting spec: `/Users/genome/projects/genomes_agentic_os/spec/update-channel.md`

## Current Anchors

- Scaffolding: `/Users/genome/projects/genomes_agentic_os/src/genomes_agentic_os/scaffold.py`
- Docs update behavior: `/Users/genome/projects/genomes_agentic_os/src/genomes_agentic_os/scaffold.py`
- Migrations: `/Users/genome/projects/genomes_agentic_os/src/genomes_agentic_os/migrations.py`
- Doctor checks: `/Users/genome/projects/genomes_agentic_os/src/genomes_agentic_os/doctor.py`
- Validation: `/Users/genome/projects/genomes_agentic_os/src/genomes_agentic_os/validate.py`
- CLI surface: `/Users/genome/projects/genomes_agentic_os/src/genomes_agentic_os/cli.py`
- Update command guide: `/Users/genome/projects/genomes_agentic_os/harness/commands/os-update.md`
- Test coverage: `/Users/genome/projects/genomes_agentic_os/tests/test_cli_scaffold.py`

## Orchestration Prompt

```text
/orchestrate

Work in /Users/genome/projects/genomes_agentic_os.

Goal: finish Plan 19, "Update Channel And Customer Fleet", by defining and implementing the future update-channel contract: update identity, policy, manifests, check/plan/apply/rollback/status, phone-home safety, and local control-plane visibility.

Primary spec:
/Users/genome/projects/genomes_agentic_os/PLANS/19-update-channel-and-customer-fleet.md

Supporting spec:
/Users/genome/projects/genomes_agentic_os/spec/update-channel.md

Important repo context:
- This repo is the source package, not the live installed OS.
- The live install target is ~/agentic_os.
- Plan 20 is the simpler operator-pushed V1 path and may be implemented before or beside Plan 19.
- Do not build hosted fleet infrastructure unless the user explicitly asks. Keep the first slice local and file-backed.
- The worktree may be dirty. Do not revert user changes or unrelated edits. Work with concurrent changes.

Start with read-only investigations. Do not begin implementation workers until the investigation outputs identify the smallest safe first build slice.

Baseline first:
1. Capture `git status --short` and `git rev-parse HEAD`.
2. Run `uv run pytest -q` if the environment is ready. If blocked, record the exact blocker and continue with read-only investigation.
3. Inspect Plan 19, spec/update-channel.md, scaffold.py, migrations.py, doctor.py, validate.py, cli.py, harness/commands/os-update.md, and tests.

Investigation requirements:
1. Update identity audit: define `.agentic_root`, `agentic-os.lock.json`, update channel, install id, policy, and local status shape.
2. Manifest and plan model: define update manifest schema, check/plan behavior, additive update classification, risky change classification, and stable plan output.
3. Apply and rollback model: define safe additive apply, local edit protection, rollback snapshots, post-update doctor checks, and failure recovery.
4. Phone-home safety: define heartbeat-safe payloads that exclude prompts, customer files, source code, logs, secrets, and raw customer data.

Expected implementation strategy:
- Keep Plan 19 local-first and file-backed.
- Treat phone-home as a payload generator first, not a network sender.
- Reuse additive managed-asset behavior from docs updates.
- Block executable, hook, MCP, rule, permission, delete, overwrite, and credential changes unless policy approves.
- Make update status inspectable locally and mirrorable into Notion later.

Likely first build slice:
Implement update metadata and dry-run planning:
- add update metadata to fresh installs,
- seed `UPDATE_POLICY.md` and `registries/updates.yml`,
- add an update manifest schema,
- add `agentic-os update check` and `agentic-os update plan` as non-mutating commands,
- classify safe additive versus blocked risky changes,
- add tests that prove local edits are not overwritten.

Worker rules:
- You are not alone in this codebase. Other agents or the user may be editing files concurrently.
- Do not revert edits made by others.
- Adjust your implementation to accommodate concurrent changes.
- Edit files directly when assigned an implementation slice.
- List every changed file in your return.
- Include exact commands run and exact test results.

Verification target:
- `uv run pytest -q`
- `agentic-os init --target <temp root> --projects-source <temp projects>`
- `agentic-os update check --root <temp root>`
- `agentic-os update plan --root <temp root>`
- `agentic-os validate --root <temp root>`

Return first:
1. Investigation summary.
2. Recommended build slices.
3. Files each slice should own.
4. Risks or user approvals needed.
5. The first implementation slice ready for worker dispatch.
```

## Investigation Prompts

### 1. Update Identity And Policy

```text
Read-only investigation in /Users/genome/projects/genomes_agentic_os.

Define the local update identity and policy contract.

Focus on `.agentic_root`, `agentic-os.lock.json`, update channel, install id, local status, `UPDATE_POLICY.md`, `registries/updates.yml`, and customer-specific policy overrides.

Return schema, install changes, validation checks, and tests.

Do not edit files.
```

### 2. Manifest, Check, And Plan

```text
Read-only investigation in /Users/genome/projects/genomes_agentic_os.

Design update manifest parsing and non-mutating planning.

Focus on manifest schema, source refs, version/channel matching, safe additive changes, risky blocked changes, stable plan files, and local edit detection.

Return command design, code owners, and tests.

Do not edit files.
```

### 3. Apply, Rollback, And Doctor

```text
Read-only investigation in /Users/genome/projects/genomes_agentic_os.

Design safe update application and rollback.

Focus on additive application, no-overwrite behavior, rollback snapshot contents, post-update doctor checks, failure recovery, and run logs.

Return implementation slices and validation commands.

Do not edit files.
```

### 4. Phone-Home Payload Safety

```text
Read-only investigation in /Users/genome/projects/genomes_agentic_os.

Design heartbeat-safe phone-home metadata generation.

Focus on approved operational metadata, explicit exclusions, privacy boundaries, local preview, Notion/control-plane mirroring, and policy gates before any network send.

Return payload schema, command behavior, tests, and approval requirements.

Do not edit files.
```

## Initial Findings

- Plan 19 is P1 and broader than Plan 20.
- Supporting spec work exists at `spec/update-channel.md`, and an `os-update` command guide already exists.
- The likely first implementation should be dry-run update check/plan plus local metadata, with apply/rollback and phone-home sender deferred behind policy gates.
