---
name: los-deploy-watch
description: Watch LOS #los_deployment for bounded deploy/build failure windows, attribute failures to recent Michael Clark merges, check migration risk, and route guarded environment repair PRs.
---

# LOS Deploy Watch

Use this skill when the user asks to run `los-deploy-watch`, watch
`#los_deployment`, monitor LOS deploy failures after merges, or investigate
whether a Michael Clark merge or migration caused a LOS environment build/deploy
failure.

## Procedure

1. Start from `/Users/genome/agentic_os`.
2. Load the OS and LOS routing context before acting:
   - `ROUTER.md`, `CONTEXT.md`, `RULES.md`, `TOOLS.md`
   - `los/ROUTER.md`, `los/CONTEXT.md`, `los/RULES.md`, `los/TOOLS.md`
   - `los/00-programs/los_deploy_watch/program.md`
   - `los/00-programs/los_deploy_watch/runbook.md`
   - `los/03-workflows/engineering/los_deploy_watch/workflow.md`
   - `los/03-workflows/engineering/los_deploy_watch/runbook.md`
3. Verify Slack access to `#los_deployment` (`C023BPFHYH2`).
4. Create or reuse a run folder under the active LOS app work item:
   `los/02-projects/los_app_los_django/work-items/02-active/099_los_deploy_watch/artifacts/los-deploy-watch/`.
5. Prefer the local runner when a Slack Web API token can read the channel:

   ```bash
   python3 los/00-programs/los_deploy_watch/scripts/los_deploy_watch.py \
     --channel-id C023BPFHYH2 \
     --channel-name los_deployment \
     --duration-minutes 60 \
     --interval-seconds 60 \
     --output-dir <run-folder>
   ```

6. If the local Slack token cannot read the channel, use the Slack MCP/connector
   in a Codex or Claude heartbeat/check loop and record that fallback in the run
   artifact.
7. If a deploy/build failure appears, inspect recent PRs in
   `thesummitgrp/los-app-los-django` authored by or merged by the current GitHub
   user around the failure time. Check changed files under `*/migrations/*`
   first.
8. Open a repair PR only when evidence clearly ties the failure to a safe code
   fix and the environment target branch is clear. Hand the PR to
   `pr_watch_repair_loop`.
9. Do not merge, deploy, apply migrations, run SQL, restart services, or post
   Slack/Jira/GitHub comments with local paths or private Notion links.

## Outputs

- Run state, event, and summary artifacts.
- Notion projection update after Genome's Notion verification.
- Optional repair PR URL when evidence supports one.
- Blocker summary when evidence is missing or ambiguous.
