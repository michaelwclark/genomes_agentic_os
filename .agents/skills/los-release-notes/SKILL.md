---
name: los-release-notes
description: Build LOS app release notes from the latest production build commit and all PRs targeting a requested release or hotfix branch.
---

# LOS Release Notes

Use this skill when the user asks for LOS release notes for a version such as
`9.12.4`.

## Procedure

1. Start from `/Users/genome/agentic_os`.
2. Load the LOS routing context before acting:
   - `ROUTER.md`, `CONTEXT.md`, `RULES.md`, `TOOLS.md`
   - `los/ROUTER.md`, `los/CONTEXT.md`, `los/RULES.md`, `los/TOOLS.md`
   - `los/03-workflows/engineering/los_release_notes/quick-reference.md`
   - `los/03-workflows/engineering/los_release_notes/runbook.md`
3. Read the canonical LOS version registry and require a fresh, healthy,
   resolvable production boundary. Use the production health-check SHA as the
   lower bound; never use the whole hotfix branch as release membership.
4. Run:

   ```bash
   python3 los/03-workflows/engineering/los_release_notes/scripts/build_release_notes.py --version <version> --assume-open-prs
   ```

5. Read the generated `release-notes.md` artifact and return the artifact path
   plus the concise release-note summary.
6. Do not publish to Jira, GitHub, Slack, email, or Notion unless the user
   explicitly asks for that write and the target workspace/account is verified.

## Defaults

- `9.12.4` maps to `hotfix/v9.12.4`.
- Open target PRs are included as assumed release contents when the user says to
  assume the release PRs will land.
- Closed unmerged PRs are excluded unless the user asks for superseded history.
