# Holdout QA Results

## Full Suite

```text
$ uv run --extra dev pytest -q
.......................................                                  [100%]
39 passed in 3.07s
```

## Notion Sync Smoke

Plan summary:

```text
workspace=Genome's Notion; actions=29; kinds=active_work,approvals,automation,decisions,domain,metrics,project,run,workflow; creates=29
```

Apply without verified workspace:

```text
refuse_exit=2; refuse=error: cannot apply Notion sync without verified workspace: expected "Genome's Notion"
```

Apply with verified workspace:

```text
workspace=Genome's Notion; applied=None; actions=29; mapping=/private/tmp/agentic-os-notion-sync-holdout3-m3ZgpP/os/.notion-sync/mapping.yml
```

Dry run after apply:

```text
workspace=Genome's Notion; dry_run=None; actions=29; no_ops=29; creates=0; updates=0
mapping present
```
