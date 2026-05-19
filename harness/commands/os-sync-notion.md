# OS Sync Notion

Use when preparing to sync the filesystem OS to a Notion control panel.

## Procedure

1. Verify the target Notion workspace is Genome's Notion or an explicitly selected client workspace.
2. Read `domain.yml` for Notion page and database IDs.
3. Map domain active work to Notion dashboard entries.
4. Map runs to Notion run records.
5. Map approvals to Notion approval records.
6. Preserve filesystem files as source links.
7. Do not create fallback pages in the wrong workspace.

## Output

Prepare a sync plan with target pages, records to create or update, and approval needs.
