# Build Runner Memory Log

## 00 Current State And Gap Map

- Notion connector was unauthorized; direct API fallback worked.
- Use `uv run` for verification because `python` is not on PATH in the context shell.
- The root worktree was dirty before this run; next build-runner work should start from a clean commit or explicit dirty-baseline approval.

## 01 Project Create And Active Work

- Worktree-local `uv run pytest` needed `--extra dev` when the worktree venv was fresh.
- Project create should stay additive: do not rewrite project files; append missing index/source rows only.

## 02 Routing And Context Builder

- Deterministic routing can use project `sources.repo` to map external cwd values back into the installed OS project tree.
- Route commands are read-only by default; context packets are printed YAML.

## 18 Documentation And Help Guide For 00 Current State And Gap Map

Feature guide docs currently live under `docs/13-feature-guides/`. Feature 00 documentation should explain source/runtime boundaries and the plan mirror path rather than introducing new runtime commands.

## 19 Holdout Command Validation For 00 Current State And Gap Map

Feature 00 holdout checks should avoid live Notion writes and prefer local source, runner-state, and disposable-runtime evidence.

## 20 Documentation And Help Guide For 01 Project Create And Active Work

Project-create guidance should emphasize additive writes, active-work discovery, source-map references, and `lenders` to `los` alias behavior.

## 21 Holdout Command Validation For 01 Project Create And Active Work

Feature 01 holdout validation should check active-work/project indexes, source-map rows, idempotency, and `lenders` to `los` aliasing.

## 22 Documentation And Help Guide For 02 Routing And Context Builder

Routing/context docs should emphasize read-only defaults and low-confidence failure instead of guessing.

## 23 Holdout Command Validation For 02 Routing And Context Builder

Routing holdouts should check target path/source text, approval risk text, linked-repo `here` detection, low-confidence failure, and root validation.

## 24 Documentation And Help Guide For 03 Workflow Readiness And Run Closeout

workflow closeout docs should stress validation required for done and local writebacks.

## 25 Holdout Command Validation For 03 Workflow Readiness And Run Closeout

feature 03 holdouts should check validation-required done closeout and writebacks.

## 26 Documentation And Help Guide For 04 Automation Maturity And Reconfiguration

automation maturity docs should stress conservative levels and local writebacks.

## 27 Holdout Command Validation For 04 Automation Maturity And Reconfiguration

automation maturity holdouts should include both the blocked unsafe promotion
path and the safe `prepare` path.

## 28 Documentation And Help Guide For 05 Customer Os Factory

customer OS factory docs should distinguish blocking `core_errors` from
non-blocking `profile_warnings`, including private source-term warnings.

## 29 Holdout Command Validation For 05 Customer Os Factory

customer factory holdouts should scan generated markdown and YAML for private
source-owner terms after init/update/validate.

## 30 Documentation And Help Guide For 06 Notion Control Plane Sync

Notion sync docs should keep filesystem source of truth and Notion control
plane boundaries explicit.

## 31 Holdout Command Validation For 06 Notion Control Plane Sync

Notion sync holdouts should verify workspace refusal and post-apply no-op dry
run behavior without requiring a live Notion write.

## 32 Documentation And Help Guide For 07 Doctor Validation And Migrations

doctor docs should stress that `--fix-missing` is additive only, while
migration docs should stress stable preview before apply.

## 33 Holdout Command Validation For 07 Doctor Validation And Migrations

doctor/migration holdouts should include missing-plan and changed-target apply
refusals as well as successful re-plan/apply.

## 34 Documentation And Help Guide For 08 Losmon Replacement Validation

LOSMon replacement docs should not imply parity; keep comparison gaps visible
until real read-only validation exists.

## 35 Holdout Command Validation For 08 Losmon Replacement Validation

LOSMon holdouts should check generated project, three workflows, thread intake,
three run logs, comparison gap table, repo capture, and root validation.

## 36 Documentation And Help Guide For 09 Future Ideas Intake

future ideas docs should emphasize durable additive capture, not immediate
promotion to active work.

## 37 Holdout Command Validation For 09 Future Ideas Intake

plan capture holdouts should inspect target files for captured titles.

## 38 Documentation And Help Guide For 10 Notion Control Plane Bootstrap

bootstrap docs should state that apply requires both verified workspace and
approved parent page ID.

## 39 Holdout Command Validation For 10 Notion Control Plane Bootstrap

bootstrap holdouts should verify both missing-parent refusal and Michael Clark
personal Notion refusal before accepting verified Genome's Notion apply.

## 40 Documentation And Help Guide For 11 Room First Installer And Routing

room-first docs should distinguish operational rooms from shared runtime docs
and keep Claude/Codex pointer behavior tied to `ROUTER.md`.

## 41 Holdout Command Validation For 11 Room First Installer And Routing

room-first holdouts should use profile `tools` entries as mappings, not plain
strings, and should treat `shared_factory` as shared docs rather than a default
operational domain.

## 42 Documentation And Help Guide For 12 Factory Template Import Backlog

factory template docs should keep source import policy separate from runtime
template installation paths.

## 43 Holdout Command Validation For 12 Factory Template Import Backlog

factory template holdouts should test source policy docs separately from
installed runtime template paths.

## 44 Documentation And Help Guide For 13 Reference And Skill Index Layer

reference layer docs should tie runtime references to
`shared_factory/05-knowledge/references/` and skill alignment to the source
skill registry.

## 45 Holdout Command Validation For 13 Reference And Skill Index Layer

reference-layer holdouts should treat `decision-log.md` as installed and
validated, while the context packet contract covers naming, tool index, source
priority, and style/output references.

## 46 Documentation And Help Guide For 14 Client Automation And Control Plane Playbooks

client playbook docs should keep automation-fit analysis separate from
automation creation and preserve verified Notion workspace guardrails.

## 47 Holdout Command Validation For 14 Client Automation And Control Plane Playbooks

client playbook holdouts should verify additive restoration, local edit
preservation, and validation failure for missing required command prompts.

## 48 Documentation And Help Guide For 15 Always On Runtime Heartbeats Schedules And Integrations

Feature 15 runtime operations are documented at docs/13-feature-guides/15-always-on-runtime-heartbeats-schedules-and-integrations.md. The guide anchors operators on file-backed heartbeats, schedules, integrations, and guarded Notion runtime tracking.

## 49 Holdout Command Validation For 15 Always On Runtime Heartbeats Schedules And Integrations

Feature 15 holdout confirms docs update restores managed runtime knowledge, runtime and heartbeat/schedule commands are file-backed, and Notion runtime tracking must be guarded by verified workspace before local apply.

## 50 Documentation And Help Guide For 16 Connected Source Watch Registry

Feature 16 is documented at docs/13-feature-guides/16-connected-source-watch-registry.md. The guide anchors operators on connected systems, source providers, watch sources, cursors, source events, and dry-run/apply behavior.

## 51 Holdout Command Validation For 16 Connected Source Watch Registry

Feature 16 holdout confirms watch-source apply writes source-events and cursor state locally, and doctor catches missing cursor/dedupe metadata.

## 52 Documentation And Help Guide For 17 Event Graph And Chained Automations

Feature 17 is documented at docs/13-feature-guides/17-event-graph-and-chained-automations.md. Chain rules are file-backed registry entries tested by chain test/doctor, then processed by event process-due.

## 53 Holdout Command Validation For 17 Event Graph And Chained Automations

Feature 17 holdout confirms event process-due apply writes queue work and idempotency state, repeated apply skips duplicates, replay works, dead-letter records are written for broken enabled rules, and run closeout can emit event evidence.

## 54 config.toml Options Inventory And Analysis

The canonical Codex config research now lives in docs/07-agent-surfaces/codex-config-toml-inventory.md. The reusable layer IDs for profile and installer follow-up work live in templates/agent-config/codex-config-layer-map.yml.
