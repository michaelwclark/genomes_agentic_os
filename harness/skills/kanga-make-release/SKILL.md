---
name: kanga-make-release
description: Cut a Kanga release — promote develop (beta) to main (production channel) across all five Kanga repos (backend, both webs, both Flutter apps) with preflight checks, release PRs, semantic-release verification, and gated production/store deploy handling. Use when the user asks to make/cut/ship a Kanga release, promote Kanga develop to main, or asks for Agentic OS `kanga-make-release` work.
---

# Kanga Make Release

Codified release workflow for all five Kanga repos on canonical gitflow
(`KANGA-BOOKING/kanga-backend`, `kanga-user-web`, `kanga-business-web`,
`kanga-user-app`, `kanga-business-app`). The mobile repos joined under the
2026-07-17 unification mandate (KAN-159/152/160/162). KAN-159 completed the
mobile `develop`-branch reconciliation; current readiness comes from the live
preflight and remaining release/deploy prerequisites. Narrow a run with
`--repos`.

The pipeline this drives (epic KAN-142):

- `develop` push → CI + **beta** deploy (automatic; web/backend = beta
  servers, mobile = Play internal track/TestFlight; deploy secrets are live
  in all five pipeline repos since 2026-07 under KAN-151/store custody, so
  beta lanes really deploy)
- `main` push → CI + semantic-release (stable `vX.Y.Z` tag, GitHub Release
  notes from the conventional-commit log) + **production** deploy, which is
  **gated**: it runs only via `workflow_dispatch` (push-button) or when repo
  variable `AUTO_DEPLOY_PROD=true`. For mobile, "production deploy" means
  store submission — it ends at "submitted"; store review is outside CI.

## Load

1. Route to `domains/clarks_consulting/02-projects/kanga/` and read `CONTEXT.md`,
   `RULES.md`, `TOOLS.md`, and `status.md`.
2. Read `docs/RELEASING.md` in each target repo (repo doc wins on mechanics).
3. `memory_read` for recent Kanga release/CI state before acting.

## Usage

```text
/kanga-make-release                 # preflight only (read-only report)
/kanga-make-release cut             # preflight + cut release branches + open PRs
/kanga-make-release all             # full run: preflight → cut → merge → watch
/kanga-make-release --repos kanga-backend all
/kanga-make-release all --prod-dispatch   # additionally dispatch PRODUCTION deploys
```

Driver: `harness/skills/kanga-make-release/scripts/make_release.sh`
(`--phase preflight|cut|merge|watch|all`, `--repos a,b,c`, `--prod-dispatch`,
`--output-dir`). Receipts land in
`domains/clarks_consulting/02-projects/kanga/artifacts/releases/<date>/`.

## Procedure

1. **Preflight** (`--phase preflight`, default; read-only). Per repo: latest
   `develop` CI green; `main...develop` ahead-only (behind=0); `ci.yml` +
   `deploy.yml` + `release.yml` present on `develop`; `beta`+`production`
   environments exist; report `AUTO_DEPLOY_PROD`; warn on bare legacy tags
   (KAN-154). Do not proceed past a preflight FAIL — fix the cause.
2. **Queued work check** (judgment, not scripted): confirm no release-blocking
   PRs are still open against `develop` (Release 1.0 set, KAN-154 dual-channel
   PRs, mobile KAN-152 lane PRs). Merge those first
   or scope them out consciously. Mobile also needs its semver baseline tag
   (KAN-160: tag the merged develop head with the store version — user-app
   `v2.0.13`, business-app `v1.0.9`) before its first release.
3. **Cut** (`--phase cut`): branch `release/<UTC-date>` from `develop` head,
   open PR → `main` titled `release: promote develop to main (<date>)`.
   Idempotent — reuses an existing branch/PR.
4. **Merge** (`--phase merge`): waits for the release PR's checks, then merges
   with a **merge commit — never squash**. semantic-release computes the
   version from the individual conventional commits that land on `main`;
   squashing collapses them into one message and mis-versions the release.
5. **Watch** (`--phase watch`): waits for the `Release` workflow on `main`,
   reports the new tag + GitHub Release, and reports the `Deploy` run —
   which must show production **skipped/gated** unless dispatched.
6. **Deploy**: beta deploys happened automatically on the develop pushes.
   Production is a deliberate act:
   `gh workflow run deploy.yml -R KANGA-BOOKING/<repo> --ref main -f environment=production`
   (or pass `--prod-dispatch`; or flip `AUTO_DEPLOY_PROD=true` to make `main`
   auto-deploy). `--ref main` is **not** optional: a dispatch without `--ref`
   runs the repo's **default branch** — `develop` on all five repos — so it
   builds develop's unreleased tree and ships it into the production
   environment. Deploy secrets are live (KAN-151, 2026-07): every dispatched
   deploy is a real production action, not a dry run.

## Closeout

- Comment the release (tags, PR links, deploy outcome) on
  [KAN-153](https://linear.app/genomes/issue/KAN-153) the first time
  this promotes workflows to `main`, and on the release-coordination surface
  (`Kanga AWS / Infra / Ops` project) thereafter.
- Append the release row to `domains/clarks_consulting/02-projects/kanga/status.md`
  (Recent Activity) and record any 50/50 call in `decisions.md`.
- Capture durable surprises with `memory_write`.

## Safety

- Never force-push or rewrite `develop`, `main`, `release/*`.
- Release PRs merge with merge commits only (see Procedure step 4).
- Never dispatch a production deploy implicitly; `--prod-dispatch` or the
  `AUTO_DEPLOY_PROD` variable is the only path. Deploy secrets are live
  (KAN-151, provisioned 2026-07), so both paths touch real servers and
  stores; secret values stay in `secrets/kanga.prod.env` custody — never in
  git, Linear, Notion, or chat.
- Every manual production dispatch pins `--ref main`. Without `--ref`,
  `gh workflow run` uses the repo's default branch (`develop`) — wrong code
  into production.
- No agentic files in the five Kanga repos; this skill lives only in the OS.
