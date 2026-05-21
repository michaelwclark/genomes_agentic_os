# Investigation

- Filesystem state already contains enough structure to plan Notion records without live credentials.
- Live Notion writes are unsafe unless the workspace is verified, so apply requires an explicit verified workspace value.
- Customer roots created by feature 05 carry `customer.notion_workspace`, which can be used as the expected workspace.
