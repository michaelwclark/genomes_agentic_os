# Plan 20 Orchestration Prompt

Use this prompt to start the Plan 20 orchestration run as the practical V1 update path for customer installs.

## Source Spec

- Spec: `/Users/genome/projects/genomes_agentic_os/PLANS/20-operator-pushed-customer-updates-and-backups.md`
- Companion prompt: `/Users/genome/projects/genomes_agentic_os/PLANS/20-operator-pushed-customer-updates-and-backups.orchestration.md`
- Supporting spec: `/Users/genome/projects/genomes_agentic_os/spec/operator-pushed-customer-updates.md`

## Current Anchors

- Customer install/update code: `/Users/genome/projects/genomes_agentic_os/src/genomes_agentic_os/customer.py`
- Scaffolding and docs update behavior: `/Users/genome/projects/genomes_agentic_os/src/genomes_agentic_os/scaffold.py`
- Validation: `/Users/genome/projects/genomes_agentic_os/src/genomes_agentic_os/validate.py`
- Doctor checks: `/Users/genome/projects/genomes_agentic_os/src/genomes_agentic_os/doctor.py`
- CLI surface: `/Users/genome/projects/genomes_agentic_os/src/genomes_agentic_os/cli.py`
- Update command guide: `/Users/genome/projects/genomes_agentic_os/harness/commands/os-update.md`
- Test coverage: `/Users/genome/projects/genomes_agentic_os/tests/test_cli_scaffold.py`

## Orchestration Prompt

```text
/orchestrate

Work in /Users/genome/projects/genomes_agentic_os.

Goal: finish Plan 20, "Operator-Pushed Customer Updates And Backups", by building the simpler V1 path for customer-local update keys, backup keys, license activation, billing-gated grants, safe additive update pulls, backup planning, backup run logs, and validation.

Primary spec:
/Users/genome/projects/genomes_agentic_os/PLANS/20-operator-pushed-customer-updates-and-backups.md

Supporting spec:
/Users/genome/projects/genomes_agentic_os/spec/operator-pushed-customer-updates.md

Important repo context:
- This repo is the source package, not the live installed OS.
- The live install target is ~/agentic_os.
- This is the practical V1 path. Keep it simpler than Plan 19 fleet automation.
- Never print license keys, API keys, private SSH keys, env files, secrets, or raw customer data.
- The worktree may be dirty. Do not revert user changes or unrelated edits. Work with concurrent changes.

Start with read-only investigations. Do not begin implementation workers until the investigation outputs identify the smallest safe first build slice.

Baseline first:
1. Capture `git status --short` and `git rev-parse HEAD`.
2. Run `uv run pytest -q` if the environment is ready. If blocked, record the exact blocker and continue with read-only investigation.
3. Inspect Plan 20, spec/operator-pushed-customer-updates.md, customer.py, scaffold.py, validate.py, doctor.py, cli.py, harness/commands/os-update.md, and tests.

Investigation requirements:
1. Customer identity and license audit: define customer identity, fake license activation, non-secret metadata, and test-safe billing responses.
2. SSH grant model: define update key and backup key generation, separation of identities, public-key-only registration, and never-store/never-print private material.
3. Update pull model: define `update register`, grant storage, fake active/inactive billing behavior, update remotes, safe additive plan/apply, and blocked risky changes.
4. Backup model: define backup policy, exclusions, local run logs, remote push skipping in tests, doctor/validate health, and customer data boundaries.

Expected implementation strategy:
- Keep everything local and fake-provider friendly for tests.
- Store only non-secret license metadata.
- Generate update and backup SSH identities separately.
- Send or record only public keys during registration.
- Reuse additive managed-asset behavior from docs update.
- Exclude private keys, env files, secrets, raw customer data, and `projects/` from backup by default.

Likely first build slice:
Implement local customer identity, license activation, update registration, and grant validation:
- seed `registries/customer-identity.json`,
- create `registries/update-grant.json` only after registration,
- create `registries/backup-policy.yml`,
- create `security/ssh/` and `logs/{updates,backups}/`,
- add fake billing response fixtures,
- add `agentic-os license activate` and `agentic-os update register`,
- add tests that prove secrets are never printed and inactive billing blocks registration.

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
- `agentic-os license activate --root <temp root> --key <fake key>`
- `agentic-os update register --root <temp root> --billing-fixture <fake active>`
- `agentic-os update plan --root <temp root> --source os-upstream`
- `agentic-os backup plan --root <temp root>`
- `agentic-os validate --root <temp root>`

Return first:
1. Investigation summary.
2. Recommended build slices.
3. Files each slice should own.
4. Risks or user approvals needed.
5. The first implementation slice ready for worker dispatch.
```

## Investigation Prompts

### 1. Customer Identity And License Activation

```text
Read-only investigation in /Users/genome/projects/genomes_agentic_os.

Design the customer identity and license activation contract.

Focus on `registries/customer-identity.json`, non-secret license metadata, fake license keys for tests, output redaction, and validation findings.

Return schema, CLI design, tests, and redaction rules.

Do not edit files.
```

### 2. Update And Backup SSH Grants

```text
Read-only investigation in /Users/genome/projects/genomes_agentic_os.

Design the local SSH grant model.

Focus on separate update and backup identities, `security/ssh/`, public-key-only registration, `registries/update-grant.json`, fake billing responses, active/inactive grant behavior, and private-key protection.

Return implementation slices, tests, and safety rules.

Do not edit files.
```

### 3. Safe Update Pulls

```text
Read-only investigation in /Users/genome/projects/genomes_agentic_os.

Design customer-safe update plan/apply behavior.

Focus on read-only update remotes, additive managed assets, local edit protection, blocked risky changes, no-overwrite behavior, run logs, and relationship to Plan 19.

Return code owners, command shape, and tests.

Do not edit files.
```

### 4. Backup Policy And Run Logs

```text
Read-only investigation in /Users/genome/projects/genomes_agentic_os.

Design backup plan/push behavior.

Focus on `registries/backup-policy.yml`, default exclusions, private key and secret protection, raw customer data boundaries, separate backup remote, local backup run logs, and skipped remote push behavior in tests.

Return schema, command behavior, doctor checks, and tests.

Do not edit files.
```

## Initial Findings

- Plan 20 is P0 and should likely land before the broader Plan 19 hosted/fleet concepts.
- Supporting spec work exists at `spec/operator-pushed-customer-updates.md`.
- The likely first implementation is local identity/license/update registration with fake billing fixtures, separate SSH identities, secret redaction, and validation before update apply or backup push behavior.
