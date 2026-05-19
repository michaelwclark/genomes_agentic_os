# Good Examples

## Good Project README

```markdown
# Project: LOS Release Readiness

## Outcome

Prepare and validate the release path for the named LOS release.

## Source Systems

| Source | Link | Use |
| --- | --- | --- |
| GitHub |  | PRs and CI |
| Jira |  | Scope and release notes |

## Workflows

- `03-workflows/engineering/release_review/`

## Current Status

| Status | Next Action | Owner |
| --- | --- | --- |
| active | Validate open PRs and deployment state. | OS Owner |
```

## Good Automation Permission

```markdown
| Action | Allowed Level | Approval |
| --- | --- | --- |
| Read Slack thread | observe | no |
| Draft reply | prepare | no |
| Send reply | execute_approved | yes |
```

## Good Run Final State

```markdown
## Final State

status: waiting_for_approval
next_action: Human review of drafted customer update.
evidence:
- validated source links
- generated draft artifact
- no external send performed
```
