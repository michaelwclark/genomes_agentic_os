# composio-debug-bundle

Set per-user Composio support/debug identifiers for local runtime diagnostics.

## Environment Variables

- `COMPOSIO_DEBUG_PROJECT_ID`
- `COMPOSIO_DEBUG_ORG_ID`
- `COMPOSIO_DEBUG_ORG_MEMBER_EMAIL`
- `COMPOSIO_DEBUG_USER_ID`

## Setup

From explicit flags:

```bash
./installers/set-composio-debug-bundle.sh \
  --project-id '<project_id>' \
  --org-id '<org_id>' \
  --org-member-email '<org_member_email>' \
  --user-id '<user_id>'
```

From a Composio debug bundle:

```bash
cat <<'EOF' | ./installers/set-composio-debug-bundle.sh
@project_id: <project_id>
@org_id: <org_id>
@org_member_email: <org_member_email>
@user_id: <user_id>
EOF
```

## Guardrails

- Never print values in automation output; print variable names only.
- Append to the user's shell environment file instead of editing in place.
- Do not commit generated `.env` files or user-specific `.zshenv` files.
- These IDs are not API credentials, but they still identify an account context.
