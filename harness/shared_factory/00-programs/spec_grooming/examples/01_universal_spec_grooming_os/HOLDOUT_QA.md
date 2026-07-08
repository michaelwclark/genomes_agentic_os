# Holdout QA: Universal Spec Grooming OS

| Risk | Check | Expected Result |
| --- | --- | --- |
| Intent drift | Compare `ORIGINAL_INTENT.md` to final spec. | Anchors survive. |
| Duplicate work | Inspect discovery table and route decision. | Existing surfaces are reused or extended. |
| Projection leak | Review Linear/Jira draft text. | No private local paths or Notion links. |
| Jira route bypass | Try a LOS Django story. | Routes to `$jira-product-orchestrator`. |

