# Agentic OS Current-State Analysis - 2026-06-15

## Scope

This is a point-in-time audit of `/Users/genome/projects/genomes_agentic_os`
after a large amount of follow-on work. The goal is to recover where the OS
actually landed, identify stale assumptions from earlier planning, and recommend
the next useful sequence.

Evidence checked:

- Current git status and recent commits.
- Current `agentic-os --help` command surface.
- Plan/spec inventory.
- Python module inventory.
- Fresh temp-root install and validation smoke.
- Fresh scaffold context-file check.
- Live `~/agentic_os` root context-file check.
- Full test suite.

Memory note: project memory lookup returned no relevant hits, so this report is
based on current repo evidence rather than prior memory.

## Executive Summary

The repo is much further along than the stale May planning state. It is no
longer only a scaffold plus specs. The CLI now has implemented surfaces for
project lifecycle, thread closeout, update/license/backup/fleet, metrics, hooks,
remote SSH project sources, live Notion runtime tracking, source watchers,
events/chains, and self-improvement proposal review.

Current validation is strong:

- Full test suite: `405 passed in 48.28s`.
- Temp install smoke: `agentic-os init` into `/tmp` then `agentic-os validate`
  returned valid.

Before writing this analysis file, the current worktree was small and focused,
not chaotic:

- 5 modified files.
- 0 untracked files.
- Modified files are all around lifecycle/thread closeout and CLI/docs/tests.

This report itself is a new untracked build-log artifact.

The main context-contract finding has two different states:

- Live `~/agentic_os` is aligned with the root-start model. It has
  `.agentic_root`, `AGENTS.md`, `CLAUDE.md`, `ROUTER.md`, `CONTEXT.md`,
  `RULES.md`, and `TOOLS.md`; `CLAUDE.md` is the expected `@AGENTS.md` adapter.
- Fresh temp installs from the current source scaffold still do not create the
  root context-file set. They create the new files inside domains, but not at
  the installed OS root.

So the issue is not that the live OS is missing the base files. The issue is
source/install parity: fresh installs and validation need to catch up to the
live OS shape.

## Current Repo Shape

Top-level state includes:

- `.agentic-atlas/` - agent-facing architecture and validation inventory.
- `PLANS/` - 31 plan/orchestration files.
- `spec/` - 13 specs.
- `docs/` - 123 handbook/archive/assets files.
- `features/` - 65 feature work folders, currently extending into the 60s.
- `src/genomes_agentic_os/` - 34 Python modules.
- `schemas/` - 27 schema files.
- `templates/` - 125 template files.
- `harness/` - 55 command/skill files.
- `system/` and `templates/system/` - system shell / host tool registry surface.
- `skills/` - 2 top-level skill entries.

Recent commits show major landed work after the older planning thread:

- `feat: add thread lifecycle finalization workflow`
- remote SSH project sources merge and rollout
- live Notion runtime tracking merge and docs/tests
- stdlib Notion API client

## Current CLI Surface

Current top-level command families:

```text
init, domain, profile, room, project, workflow, host, automation, run-log,
thread, end-chat, finalize, cleanup-thread, archive, route, context, here,
customer, update, license, backup, fleet, metrics, config, hook, notion,
runtime, heartbeat, schedule, integration, doctor, migrate, losmon, plan,
self-improvement, connected-system, watch-source, event, chain, validate, docs
```

Important change from the stale model: `update`, `license`, `backup`, and
`fleet` now exist as CLI surfaces, not only specs. The module inventory confirms
implementation in `update_ops.py` with functions for update check/plan/apply,
license activation, key generation/registration, backup push, fleet push,
rollback/status, and phone-home payload generation.

## Implemented Areas

### Install / Scaffold / Validate

The temp install smoke still works and validates. The OS creates `.agentic_root`
and a valid domain structure.

Fresh source-scaffold context-file check found:

- Fresh root: `.agentic_root` exists.
- Fresh root missing: `AGENTS.md`, `CLAUDE.md`, `ROUTER.md`, `CONTEXT.md`,
  `RULES.md`, `TOOLS.md`, `README.md`.
- Domain `personal/` has: `AGENTS.md`, `CLAUDE.md`, `ROUTER.md`, `CONTEXT.md`,
  `RULES.md`, `TOOLS.md`, `REFERENCES.md`, `domain.yml`.
- Domain `personal/AGENT.md` is not generated.

That means the fresh domain layer now matches the simplified harness-file
direction, but the fresh root layer does not.

The live installed OS root has already been brought into the intended shape:

- Live root: `/Users/genome/agentic_os`.
- Present: `.agentic_root`, `AGENTS.md`, `CLAUDE.md`, `ROUTER.md`,
  `CONTEXT.md`, `RULES.md`, `TOOLS.md`.
- Missing: `README.md`.
- Missing by design: `AGENT.md`.
- `CLAUDE.md` contains `@AGENTS.md`.
- Root `AGENTS.md` includes the intended startup loop: read `ROUTER.md`,
  `CONTEXT.md`, `RULES.md`, and `TOOLS.md`; classify against `ROUTER.md`;
  `cd` into a narrower directory when routed; repeat before acting.

That means live operator behavior is ahead of the current fresh-install
scaffold.

### Harness / Context Contract

The context contract exists as source material:

- `spec/harness-context-contract.md`
- `PLANS/21-harness-context-contract-and-config-toml.md`
- `config.toml.plan.md`

The intended contract is:

```text
.agentic_root
AGENTS.md
CLAUDE.md
ROUTER.md
CONTEXT.md
RULES.md
TOOLS.md
```

Live `~/agentic_os` is aligned with this contract. The source scaffold and
validation behavior are not fully aligned yet because fresh temp installs omit
the root context files while still validating successfully.

### Customer Update / Backup / Fleet

The older heavy auto-updater idea has split into practical command surfaces:

- `update`
- `license`
- `backup`
- `fleet`

The associated specs/plans exist:

- `spec/operator-pushed-customer-updates.md`
- `spec/update-channel.md`
- `PLANS/20-operator-pushed-customer-updates-and-backups.md`
- `PLANS/19-update-channel-and-customer-fleet.md`

This is now more than plan text. `update_ops.py` implements the core primitives,
including license metadata, keypair handling, fake provisioning response, SSH
config writing, update grant loading, backup push, fleet push, update apply,
rollback, status, and phone-home payload.

### Project Work / Thread Lifecycle

This area appears to be the current active work.

Implemented modules:

- `lifecycle.py`
- `thread_closeout.py`
- `work_lifecycle.py`

Current dirty files add more lifecycle cleanup:

- `project work-item sync-active`
- `project work-item finalize-lingering`
- stale terminal-status packet finalization
- global active-work symlink/container refresh

Thread commands also exist:

- `thread end`
- `thread finalize`
- `thread cleanup`
- `thread archive`
- `thread stale-finalize`
- aliases: `end-chat`, `finalize`, `cleanup-thread`, `archive`

This looks like the OS is moving toward first-class conversation/work closeout,
not just project scaffolding.

### Remote SSH / Project Sources

Recent commits indicate feature 63 landed:

- remote SSH project source registry
- `host` command
- remote sync engine
- doctor checks
- migration

Module evidence:

- `hosts.py`
- `remote_ops.py`
- project source/root helpers in lifecycle modules

This is a substantial step toward managing `~/projects` and remote customer or
host surfaces.

### Notion Runtime Tracking

Recent commits show live Notion runtime tracking landed:

- stdlib Notion API client
- runtime tracking adapter
- config install path
- docs/tests

Modules:

- `notion_api.py`
- `notion_sync.py`
- runtime tracking hooks in related ops

This is a meaningful evolution from "Notion as plan/control plane only" into
selective live runtime projection.

### Capability / System Shell / Tools

The repo now has:

- `capability_registry.py`
- `mcp_catalog.py`
- `composio_catalog.py`
- `hook_ops.py`
- `templates/system/host-tool-registry.yml`
- `templates/system/shell-shape.yml`
- `system/README.md`
- `CLAUDE_SETTINGS.json.md`
- `harness/commands/system-tool-registry.md`

There is also a doc drift: `docs/13-system-shell/` is absent in the current
docs tree, while archived docs and system templates exist. This probably needs
one reconciliation pass.

### Metrics / Self-Improvement / Conversation Logging

Implemented modules now include:

- `metrics_ops.py`
- `self_improvement.py`
- `conversation_logging.py`
- `supervisor.py`

This suggests the OS now has the beginnings of measurement, proposal-only
improvement review, conversation hook logging, and supervisor ticks.

## Current Dirty Work

Current modified files:

```text
docs/17-cli-reference.md
src/genomes_agentic_os/cli.py
src/genomes_agentic_os/lifecycle.py
src/genomes_agentic_os/scaffold.py
tests/test_thread_closeout.py
```

Diff size:

```text
5 files changed, 499 insertions(+)
```

This is focused and likely safe to finish as one logical change: lifecycle
active-work cleanup and lingering terminal packet finalization.

## Stale Or Misaligned Areas

### 1. Source/Install Context Contract Drift

The largest immediate gap is not the live OS root. The live root has the base
files. The gap is that the current source scaffold does not reproduce that
root-level contract for fresh installs.

The OS design says agents should start at the `.agentic_root`, then read root
context and route inward. Live `/Users/genome/agentic_os` supports that model.
The current fresh install only creates `.agentic_root` at root and puts context
files inside domains.

Practical effect:

- Agents starting at the live `~/agentic_os` root have the intended files and
  startup loop.
- Agents starting at a new install generated from the current source scaffold
  would not have root `AGENTS.md`, `ROUTER.md`, `CONTEXT.md`, `RULES.md`, or
  `TOOLS.md`.
- `validate` still passes on the fresh temp install, so validation is not
  enforcing source/install parity with the live root contract.

### 2. Docs Baseline Is Stale

`docs/README.md` still says:

```text
Validated baseline (2026-06-09): 53 CLI commands functional ... 97/97 tests pass
```

Current reality:

- command surface is larger
- full tests are `405 passed`
- update/license/backup/fleet/thread lifecycle surfaces exist

The handbook needs a baseline refresh.

### 3. Plans Are Not Statused Against Implemented Code

Plans 18-22 exist, but some planned items now have implementation. The plan
directory is useful, but it no longer clearly says what is done, partially done,
or stale.

Examples:

- Plan 20 customer update/backup is partly implemented.
- Plan 21 harness/context contract is implemented in the live OS root and partly
  implemented in domain scaffold, but not fully reproduced by source fresh
  installs.
- Plan 22 project work lifecycle appears actively implemented.

### 4. System Shell Surface Needs Consolidation

System shell artifacts exist, but documentation/indexing is uneven:

- `system/README.md` exists.
- `templates/system/*` exists.
- `harness/commands/system-tool-registry.md` exists.
- `CLAUDE_SETTINGS.json.md` exists.
- current `docs/13-system-shell/` does not exist.

This should either become a first-class current docs page or remain an internal
source/template surface, but it should not be half-current and half-archived.

### 5. Live OS Audit Is Partial

The live `~/agentic_os` root context-file set was checked and is aligned with
the intended base model. A full live-root `validate`/`doctor` pass was not run
as part of this report.

## Recommended Next Sequence

### P0 - Finish Current Dirty Lifecycle Work

The worktree has one focused in-progress change. Finish it before opening a new
large architecture branch.

Do:

1. Review the five modified files.
2. Confirm `project work-item sync-active` and `finalize-lingering` behavior.
3. Add any missing test cases around dry-run/apply.
4. Re-run full tests.
5. Commit as one lifecycle/active-work cleanup change.

### P0 - Sync Source Scaffold With Live Root Context Contract

Make fresh installs reproduce the live root-start model.

Do:

1. Create root `AGENTS.md`, `CLAUDE.md`, `ROUTER.md`, `CONTEXT.md`, `RULES.md`,
   `TOOLS.md`, and likely `README.md` during fresh install.
2. Keep `CLAUDE.md` as an include adapter.
3. Keep `AGENT.md` disabled by default.
4. Update `validate` to require the root file set.
5. Add a fresh-install test that proves root and domain layers both match the
   contract.

This is the most important architecture cleanup because it turns the live OS
shape into repeatable source behavior.

### P0 - Refresh Docs Baseline And CLI Reference

The docs now understate the OS.

Do:

1. Update `docs/README.md` validation baseline to current test count.
2. Update `docs/17-cli-reference.md` for new commands.
3. Make sure `update`, `license`, `backup`, `fleet`, `thread`, `host`,
   `metrics`, `hook`, and `self-improvement` are visible.
4. Add a "what is implemented vs contract-only" note where needed.

### P1 - Reconcile Plan Status

The backlog should stop implying everything is future work.

Do:

1. Add status headers or closeout notes to plans 18-22.
2. Mark implemented slices, partial slices, and deferred slices.
3. Link to feature folders and tests where implementation exists.
4. Create a small "Current OS Build State" page if the plan index is too
   detailed for daily orientation.

### P1 - Run Full Live `~/agentic_os` Doctor

The live root base files are aligned, but full live install health is still
unknown.

Do:

1. Run `agentic-os validate --root ~/agentic_os`.
2. Run relevant doctor checks.
3. Check update/license/backup/fleet registries.
4. Plan an additive `docs update` or migration only if validation finds drift.

### P1 - Decide System Shell Destination

Choose whether system shell is product-facing now.

Options:

- Promote it into current docs and CLI reference.
- Keep it as internal templates/registry only.
- Fold it under capability registry docs.

Do not leave it discoverable in templates and root files but absent from the
current handbook.

## Suggested Immediate Work Item

The next best work item is:

```text
Finish lifecycle dirty work, then sync the source scaffold/validation with the
live root context contract.
```

Reason:

- Current dirty work is small and already test-covered.
- The live OS already matches the user's mental model: start agents at
  `.agentic_root`, route inward, load `TOOLS.md`, act from the final layer.
- Fresh installs do not yet reproduce that live behavior, so the product source
  is behind the operating surface.

## Bottom Line

The OS is in a good place. It has crossed from concept/scaffold into a real CLI
with implemented runtime surfaces. The next risk is not lack of capability; it
is drift. The system now needs consolidation: finish the current lifecycle
change, make source scaffolding reproduce the live root context contract,
refresh docs and plan statuses, then run a full live install doctor pass.
