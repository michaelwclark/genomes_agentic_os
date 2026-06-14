# Thread Closeout Templates

Use these templates for `/end-chat`, `/finalize`, `/cleanup-thread`, `/archive`, and stale-thread finalization.

The filesystem work item or run log remains the source of truth. Notion is a projection, and Notion failure is recorded as a non-blocking receipt unless the workspace cannot be verified and the only requested action was a Notion write.

## Files

| File | Purpose |
| --- | --- |
| `thread.yml` | Lightweight thread state and attachment metadata. |
| `thread-closeout.yml` | Machine-readable closeout receipt. |
| `closeout.md` | Human-readable handoff summary. |
| `evidence.jsonl` | Append-only receipt events for commands, artifacts, tests, and refs. |
| `memory-write-receipts.jsonl` | Append-only durable memory write or skip decisions. |
| `notion-sync.md` | Notion projection receipt, including non-blocking warnings. |
| `archive-manifest.yml` | Archive-mode manifest after finalization. |
