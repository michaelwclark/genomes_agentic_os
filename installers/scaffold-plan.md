# Scaffold Plan

## Phase 1: Filesystem Scaffold

1. Create OS root.
2. Create root `.agentic_root`, `AGENTS.md`, `CLAUDE.md`, `ROUTER.md`, `CONTEXT.md`, `RULES.md`, `TOOLS.md`, and `README.md`.
3. Create default domain roots: `personal`, `clarks_consulting`, `los`, `shared_factory`, and `archive`.
4. Create each domain's numbered structure from `00-control-plane` through `08-archive`.
5. Copy templates into `shared_factory/05-knowledge/templates/`.
6. Validate folder shape.

## Phase 2: Domain Scaffold

1. Create domain folder.
2. Fill domain config from prompts or flags.
3. Create the domain router and control-plane files.
4. Create inbox, project, workflow, automation, knowledge, run-log, metric, and archive folders.
5. Register Notion mappings in `domain.yml` or `05-knowledge/source-map.md`.

## Phase 3: Agent Install

1. Install Codex skill.
2. Install Claude skill.
3. Add project/global rules pointing to the OS root.
4. Validate agents can find the OS.

## Phase 4: Notion Scaffold

1. Verify workspace and parent page.
2. Create OS Home.
3. Create standard databases.
4. Store IDs in filesystem config.
5. Create dashboard views.

## Phase 5: Runtime Expansion

Add database-backed active state only after the pilot proves the workflow shape.
