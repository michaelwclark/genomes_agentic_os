---
name: commitall
description: Commit all local changes in logical groups until the repository is clean. Use when the user asks to commit everything, make all needed commits, or cleanly commit the full worktree without pushing.
---

# Commit All

Commit all local changes in this repository in logical, cohesive groups until the working tree is clean.

## Required inspection

Run these first:

- `git status --short`
- `git diff --stat`
- `git diff --staged --stat`
- `git log --oneline -12`
- `git branch --show-current`

## Ignore rules

Treat these as out of scope unless the user explicitly asks for them:

- `.pr-body.md`
- `stgcore-app-ulp`

Do not edit, stage, commit, or mention them as work to clean up. Do not add them to `.gitignore`.

## Commit message rule

Extract a Jira key from the current branch name.

Accepted examples:

- `feature/FLYWL-1234`
- `bugfix/FLYWL-1234-something`
- `FLYWL-1234/foo`

If a Jira key is present, every commit message in this run must start with:

- `FLYWL-1234: `

If no Jira key is present, stop and ask the user for the Jira key before committing.

Keep the rest of each message concise and explain why that grouped change exists.

## Grouping workflow

1. Review the current changes and separate them by intent/scope.
2. Build cohesive groups such as:
   - backend logic
   - frontend wiring
   - tests
   - docs
   - config
3. Stage only one logical group at a time with selective adds:
   - `git add <paths>`
4. Commit that group.
5. Run `git status --short` after each commit.
6. Repeat until no tracked or untracked changes remain, excluding the ignored items above.

Do not mix unrelated files into one commit just to get clean faster.

## Safety rules

- Do not push.
- Do not use `--no-verify`.
- Do not use destructive git commands.
- Do not include secrets such as `.env`, credentials, or tokens.
- Respect repository scope rules and ignore `stgcore-app-ulp` unless explicitly requested.

## Completion output

When done, print:

- all commit SHAs and messages created in this run
- final `git status --short`

The final status should be clean aside from the explicitly ignored items if they still exist.
