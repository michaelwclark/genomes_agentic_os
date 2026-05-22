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
