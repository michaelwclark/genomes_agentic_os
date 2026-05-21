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
