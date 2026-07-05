---
name: pull-request
description: Orchestrated GitHub PR review skill. Use when the user provides a PR link or asks for a senior, blocker-focused pull request review with Jira acceptance, tests, docs, security, architecture, memory, and copy/paste GitHub markdown comments.
argument-hint: "[PR-number-or-URL] [--quick] [--severity high|medium|low] [--jira-only] [--security] [--team-health on|off] [--post]"
---

# Pull Request Review

Review GitHub pull requests with a Super Senior Graybeard Orchestrator stance: evidence first, high-risk only by default, respectful question-led comments, and no nits.

Default output includes only `HIGH` and `CRITICAL` findings. Suppress `MEDIUM` and `LOW` unless the user lowers the threshold.

## Trigger

Use this skill when:

- The user provides a GitHub PR URL, PR number, or `owner/repo#number`.
- The user asks for a PR review, pull request review, senior review, blocker-only review, Jira acceptance review, or copy/paste GitHub comments.
- The user asks whether a PR satisfies a linked Jira ticket.

If the user provides only a PR URL, treat it as an implicit review request.

## Required Workflow

1. **Memory first.** Read the local memory routing layer when available and query Unified Memory MCP/CoCoIndex with focused terms for the repo, PR number, Jira key, touched domain, changed symbols, and workflow names. Treat memory as an index, then verify claims against remote GitHub/Jira evidence before using them.
2. **Gather evidence from remotes only.** Get PR metadata, diff, files, PR body, existing comments, CI/checks, linked Jira, and any needed surrounding source from GitHub/Jira via `gh`/MCP/API. Do not treat the current local checkout as evidence for the PR. If reading many remote files would be slower than materializing them, a temporary worktree is allowed only as a read-only cache of the exact remote PR/base refs; document that choice and do not run tests, linters, builds, formatters, app commands, or manual validation commands from it.
3. **Choose lanes.** Use `references/review-lanes.md` to select only the needed specialist lenses. Do not run irrelevant reviewers for theater.
4. **Fan out when useful.** Use Codex `spawn_agent` for independent read-only lane reviews when the PR is non-trivial. Small PRs may stay on the main thread.
5. **Require structured returns.** Each lane must return finding cards matching `references/finding-schema.md`.
6. **Synthesize as Graybeard.** Deduplicate, verify, demote non-blockers, choose comment depth, and produce final copy/paste GitHub markdown.
7. **Choose final PR action.** Always include a final overall action and reviewer message: `comment`, `approve`, or `request changes`.
8. **Write back durable learning.** If the user gives follow-up calibration or durable workflow direction, write it to Unified Memory MCP and the local memory update mechanism when available.
9. **Team health hook.** If enabled by `--team-health on` or repo policy, emit structured telemetry per `references/team-health-hook.md`. Do not alter review comments or record personal judgments.

## Evidence Commands

Prefer connected GitHub/Jira MCP tools when available. Otherwise use `gh`. Pull the diff, metadata, review comments, checks, and source context straight from GitHub. The current local checkout is not authoritative evidence for the PR. `gh pr diff` and the files API return the diff computed against the PR's real base, so they sidestep stale-local-base phantom diffs.

```bash
gh pr view <pr> --json title,body,baseRefName,headRefName,headRefOid,baseRefOid,files,additions,deletions,author,commits,reviews,comments,statusCheckRollup
gh pr diff <pr>                                          # canonical unified diff vs the real base
gh api repos/<owner>/<repo>/pulls/<pr>/files --paginate  # per-file patches; good for scoping large PRs
gh pr checks <pr>
```

For changed files and surrounding code, prefer GitHub-hosted content:

```bash
gh api repos/<owner>/<repo>/contents/<path>?ref=<head-or-base-sha> --jq .content
gh api repos/<owner>/<repo>/git/trees/<sha>?recursive=1
gh api repos/<owner>/<repo>/commits/<sha>
```

Read callers, callees, interfaces, serializers, models, base classes, sibling features, and tests from the remote PR/base refs as needed to validate flow, contracts, architecture, and acceptance. You may use a temporary worktree only when it speeds up read-only inspection of exact remote refs. Do not use the user's dirty local checkout as evidence.

Do not run tests or validation commands manually during this review. CI/check status from GitHub is evidence; local `pytest`, `npm`, `yarn`, `pnpm`, `ruff`, `black`, `eslint`, build commands, management commands, app startup, or database-backed checks are out of scope. If verification is missing, report the missing CI or coverage as a review finding/question instead of trying to validate it locally.

## Severity Gate

- `CRITICAL`: likely production incident, data loss, security breach, tenant data exposure, PII/financial risk, deployment breakage, or irreversible bad migration.
- `HIGH`: likely behavior regression, real security risk, serious bad pattern, missing test for production-risky behavior, missing acceptance criterion, missing docs for new public API/Constance/config/management command, major architecture or data integrity concern.
- `MEDIUM`: useful but not blocking by default. Suppress unless requested.
- `LOW`: nit, style, local cleanup. Suppress.

When uncertain between `MEDIUM` and `HIGH`, ask: would a senior reviewer hold the PR for this? If not, suppress it.

## GitHub Comment Requirements

Every `Copy/Paste comment for GH` block must be valid GitHub-flavored markdown:

- Emit the full comment inside a fenced `markdown` code block so the user can copy/paste the whole comment cleanly.
- Use a four-backtick fence for the outer `markdown` block when the comment itself contains fenced code suggestions.
- The suggested comment location must be part of the PR diff. Before emitting `Filename` and `Line Number or method to comment on`, verify that the file is in the PR's changed-file list and that the target line appears in a diff hunk from `gh pr diff` or the GitHub files API `patch`. Do not suggest inline/file comments on unchanged files, unchanged methods, or surrounding context that GitHub will not expose as a review-comment anchor.
- Anchor suggestions to the file they affect. If the fix belongs in one file and the test or documentation work belongs in another PR file, emit separate output blocks for each file instead of burying cross-file suggestions inside one comment.
- If a real issue is caused by code outside the diff, either anchor the comment to the nearest changed diff line that introduced or fails to handle that risk, or move the issue into the final PR message as an overall/non-inline concern. Clearly say when no diff-visible inline anchor exists.
- Start with a short question-led paragraph that names the risk. Question-led means the comment asks rather than dictates — it does NOT mean a fixed opener. Vary the phrasing naturally per comment; never start every comment with the same stock phrase (e.g. "Have you considered…" on repeat reads as a template, not a reviewer).
- Use headings only when the issue is large enough to benefit from sections.
- Use bullets for options, edge cases, acceptance criteria, or verification steps.
- Use numbered lists only when order matters.
- Use fenced code blocks with language tags for suggested code.
- Use links for Jira tickets, docs, prior PRs, or pattern references when available.
- Use tables only for comparisons across cases or flows.
- Use Mermaid only for complex flow or state-machine risks.
- Keep quick fixes quick.

Do not use walls of text, vague "consider this" notes, snark, praise filler, or directives.

## Comment Depth Judge

Choose the shortest useful depth for each comment:

- **Quick**: small obvious fix. One short paragraph plus tiny code suggestion if useful.
- **Standard**: most `HIGH` findings. One or two short paragraphs, bullets for risk/fix path, one code block when useful.
- **Deep**: complex bug, security issue, architecture issue, migration/data risk, or acceptance gap. Heading, concise context, risk bullets, suggested flow/code, links or pattern references, and optional table or flowchart.

Factors: blast radius, risk type, author actionability, and reviewer readability.

## Output Format

For each final finding:

`````text
Severity: HIGH | CRITICAL | MEDIUM | LOW
Filename: path/to/file.ext
Line Number or method to comment on: L42 in diff hunk (must be diff-visible)
Copy/Paste comment for GH:
````markdown
### <Short question naming the risk — natural phrasing, varied across comments>

<Markdown-formatted comment scaled by the Comment Depth Judge. Keep suggestions scoped to this file.>

Suggested code:
```language
<small patch sketch or snippet when the fix is clear>
```
````
`````

For Quick comments, omit the heading if it feels heavy.

If no `HIGH` or `CRITICAL` findings exist:

```text
No high-severity issues found.
```

Then include a short verification note listing high-risk areas checked from remote evidence, such as Jira acceptance, GitHub CI/checks, PR body, security/tenant boundaries, migrations, docs, and memory-derived prior patterns.

## Final PR Action

Always end the review with an overall PR action and a copy/paste-ready final message:

```text
Final PR Action: comment | approve | request changes
Final PR Message:
````markdown
<Briefly name what is good, then quickly re-iterate any asks. Keep it direct and reviewer-facing.>
````
```

Action selection:

- `request changes`: use when any remaining `HIGH` or `CRITICAL` finding should block merge.
- `comment`: use when findings are non-blocking, confidence is limited by missing Jira/context, or the review has questions that do not block merge.
- `approve`: use when no blocking findings remain and the verified evidence is strong enough to approve.

Final message style:

- Start with one concise sentence on what is working well, such as focused scope, good test coverage, preserved behavior, or clean integration with existing patterns.
- Then re-iterate the asks in 1-3 short bullets or sentences.
- Do not introduce new findings in the final message. It should summarize the already listed findings and action.

## References

- `references/finding-schema.md` - required subagent finding card schema.
- `references/subagents.md` - specialist lane definitions and direct invocation names.
- `references/review-lanes.md` - change type to reviewer lane mapping.
- `references/comment-markdown.md` - markdown comment quality and depth examples.
- `references/memory-integration.md` - Unified Memory MCP and local memory rules.
- `references/team-health-hook.md` - optional team-health telemetry hook contract.
