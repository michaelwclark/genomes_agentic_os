---
schema_version: 1
provider: slack
artifact_type: any
mode: compose
destination:
  resolver: verified_workspace_and_channel
format:
  renderer: slack_markdown
  max_detail: concise
approval:
  write: explicit
validation:
  - workspace_channel_and_audience_verified
readback:
  - channel_id
  - message_timestamp
---

# Slack Standard

Lead with the outcome or ask in one sentence. Add only the decisive evidence,
impact, owner, next action, and an audience-safe canonical link. Use a thread
for detail. Do not paste ticket bodies, local receipts, or long logs.
