# Build Runner Investigation Log

## 00 Current State And Gap Map

- Verified Genome's Notion direct API access through `GENOMES_NOTION_PAT`.
- Verified `Agentic OS Kanban` database and write access.
- Found 18 live READY/Building queue cards after claiming `00`.
- Preserved existing dirty repo work and avoided overlapping edits.
- Confirmed installed runtime contains the plans directory, index, and future-ideas plan.

## 01 Project Create And Active Work

- Existing CLI had no project command.
- Existing scaffold already had domain aliases, domain project folders, active-work files, and additive write helpers.
- Implementation extends the filesystem-first scaffold with append-only project index, active-work, and source-map rows.

## 02 Routing And Context Builder

- Existing routers, context files, active-work files, and project records provide enough local source material for deterministic routing.
- Feature 01 project `sources.repo` metadata is the linked-repo detection anchor.
- Low-confidence routes should error rather than guess.

## 18 Documentation And Help Guide For 00 Current State And Gap Map

- Reviewed feature 00 audit artifacts and `PLANS/00-current-state-and-gap-map.md`.
- Confirmed documentation should be a feature guide, not a runtime behavior change.
- Worker implementation placed the guide under `docs/13-feature-guides/` and avoided runtime code changes.

## 19 Holdout Command Validation For 00 Current State And Gap Map

- Existing tests covered runtime plan installation, but no single local command checked the feature 00 acceptance contract.
- RUN_STATE uses `status: done` in the current runner file, so the validator accepts either `status` or `state` as done for compatibility.

## 20 Documentation And Help Guide For 01 Project Create And Active Work

- Reviewed feature 01 plan and closeout artifacts.
- Confirmed the guide should document command use, generated files, active-work discovery, source-map behavior, idempotency, and validation.

## 21 Holdout Command Validation For 01 Project Create And Active Work

- Project-create behavior needed a single local holdout command beyond pytest coverage.
- Validator uses a disposable root and avoids live Notion writes.

## 22 Documentation And Help Guide For 02 Routing And Context Builder

- Reviewed feature 02 artifacts, plan, tests, and routing implementation.
- Guide follows the established `docs/13-feature-guides/` pattern.

## 23 Holdout Command Validation For 02 Routing And Context Builder

- Routing behavior is visible through CLI YAML output, so holdout validation can remain local and command-driven.
- Validator uses a disposable root and linked repository path.
