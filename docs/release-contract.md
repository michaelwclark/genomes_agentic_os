# Release contract

- **Owner:** Agentic OS maintainers
- **Applies to:** Agentic OS, Harness, Library, and Brain repository roles
- **Last verified:** 2026-07-29, using GitHub provider reads
- **Status:** canonical policy; the reusable workflow is installed in Agentic OS, while the other repository roles remain pending adoption

This is the single policy source for releasing the four repository roles. Each
repository may carry a short `RELEASING.md`, but that file contains adapter values
only and links here. It must not copy this policy.

## What it does

The shared release contract standardizes the part every repository needs:

> gate → tag → GitHub release → provider readback

Build and publish remain local because the products are different. Agentic OS
publishes Python distributions, operational bundles, an SBOM, and three OCI
images. Harness publishes a packaged desktop artifact. Library publishes a
deterministic archive and validation receipts. Brain publishes release metadata.

The contract does not decide version numbers, build products, image subjects,
package formats, deployment targets, or provenance subjects. Those remain owned
by each repository adapter.

## When it runs

Repository adapters invoke the contract only after their local validation and
build gates have succeeded. Current triggers differ by design:

| Repository role | Current trigger | Tag owner | Contract mode |
| --- | --- | --- | --- |
| Agentic OS | Push of an existing `v*` tag | Maintainer | `verify` (installed) |
| Harness | Successful completion of the protected main CI workflow; manual dispatch is a smoke path | Release automation | `create` (planned) |
| Library | Push to `main`, with tag pushes also supported | Release automation after local Commitizen derivation | `create` (planned) |
| Brain | Push to `main` after promotion from `develop` | Release automation | `create` (planned) |

Agentic OS keeps maintainer-owned tags during initial adoption so the release
implementation changes without also changing version approval. Harness keeps
its proven CI-completion handoff and must shadow the contract before deciding
whether semantic release or the contract ultimately owns creation. Library
creates its tag next to the release commit produced by local version derivation.
Brain creates its tag only after promotion reaches `main`.

The Agentic OS adapter is installed in `verify` mode after mutation-free provider
dry-runs proved both an empty-release read and a complete-release no-op. Adoption
in every remaining role must start as a non-required `dry_run` shadow job. A role
moves to live creation only after the shadow readbacks match its current release
path.

## Branch roles

The policy standardizes roles, not identical branch names:

- `integration_ref` receives normal feature work.
- `release_ref` is the branch from which a release target must be reachable.

| Repository role | `integration_ref` | `release_ref` |
| --- | --- | --- |
| Agentic OS | `main` | `main` |
| Harness | `main` | `main` |
| Library | `main` | `main` |
| Brain | `develop` | `main` |

The main-only and develop-to-main topologies are both legitimate. Pending the
open product decision, the recommended default is to defer `develop` in a
main-only repository until a staging deployment or prerelease channel has a
concrete use for it. A long-lived branch without a consumer adds a back-merge
obligation without adding a promotion gate.

A future prerelease lane may add a short-lived `release/*` branch as an optional
`prerelease_ref`. It is not part of any current repository topology and must be
defined by the adopting repository before the lane is enabled.

Every release target must be reachable from `release_ref`. The contract guard
must use a GitHub compare API read, not a local shallow-clone check. The installed
Agentic OS adapter also performs a local full-fetch ancestry check before its
builds, while the reusable contract independently reads provider ancestry before
release mutation.

## Commit grammar

All release-bearing commits follow [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/).
CI must validate the pull-request commit range; a local hook is a convenience,
not the release gate. Current adoption is incomplete: Harness has only a local
commit hook; the Agentic OS required commit check runs for pull requests and is
not repeated by its tag-triggered release path; and Library's automated release
commit is pushed directly to `main` with CI skipped.

There are two similarly named toolchains:

- Agentic OS and Library use Python Commitizen.
- Harness and Brain use JavaScript commit tooling.

The exact tool versions are repository adapter concerns. Any tool that derives a
release version must be exactly pinned before that derivation is authoritative.

## Version derivation

| Repository role | Authoritative input | Derivation rule |
| --- | --- | --- |
| Agentic OS | `[project].version` in `pyproject.toml` | A maintainer changes the version in a reviewed pull request; mirrors are validated before release. |
| Harness | `package.json`, cross-checked against the application version | A maintainer changes the version in a reviewed pull request; release automation refuses disagreement. |
| Library | `VERSION` plus Conventional Commit history | Python Commitizen derives the next version, then the repository-local adapter prepares the release commit. |
| Brain | Conventional Commit history; the `package.json` cross-check is required but is not authoritative today | Semantic release derives the version; contract adoption requires the manifest cross-check to be authoritative first. |

All four products are currently pre-1.0. Agentic OS and Library use Python
Commitizen with `major_version_zero = true`; in those two repositories a
breaking change increments the minor number rather than producing `1.0.0`.
Under this setting, any `0.5.6` release maps a breaking change to `0.6.0`.
Agentic OS maintainers apply its selected number, while Library derives its own
next version from its current base. The JavaScript release toolchains do not
inherit this setting; an equivalent pre-1.0 policy must be made explicit and
tested before a breaking release is derived there.

Tags use `vX.Y.Z`. A tag is an immutable pointer: if an existing tag resolves to
a SHA other than `target_sha`, the contract fails closed and never moves it.

## Artifacts and publish targets

| Repository role | Expected release assets | Publish target |
| --- | --- | --- |
| Agentic OS | Wheel, source distribution, checksum file, release manifest containing the immutable control-plane OCI digest, image-lock receipt, emergency bundle, configuration-schema bundle, SPDX SBOM | GitHub Release plus three multi-architecture OCI images with adjacent provenance attestations |
| Harness | Verified packaged desktop archive from the completed CI run | GitHub Release |
| Library | Deterministic library archive, file manifest, validation receipt, build receipt, release-readback receipt | GitHub Release |
| Brain | Generated notes and release metadata; no binary asset manifest today | GitHub Release |

Provenance remains next to the local build because only the building repository
knows the resulting subject digests. The shared release contract does not invent
or proxy those subjects.

## Inputs and outputs

The installed reusable workflow is `.github/workflows/release-contract.yml` with
`on: workflow_call`.

### Inputs

| Input | Required/default | Meaning |
| --- | --- | --- |
| `version` | required | Version asserted by the caller |
| `tag` | `v${version}` | Release tag |
| `release_ref` | `main` | Branch that must contain `target_sha` |
| `target_sha` | caller SHA | Commit to verify or tag |
| `tag_mode` | required | `verify` for a pre-existing tag; `create` for contract-owned creation |
| `artifact_name` | empty | Workflow artifact containing release assets |
| `artifact_run_id` | caller run | Run that produced the artifact; required for cross-run retrieval |
| `asset_manifest` | empty | Newline-separated expected asset filenames |
| `notes_file` | empty | Release-notes file inside the artifact |
| `generate_notes` | `true` | Generate notes when no notes file is supplied |
| `prerelease` | `false` | Mark the release as a prerelease |
| `dry_run` | `false` | Execute every read and guard but create nothing |

### Outputs

`tag`, `version`, `target_sha`, `release_id`, `release_url`, `created`,
`repaired`, `assets_uploaded`, and `assets_receipt`. The final output is compact
JSON containing every asset name, byte size, and provider-read SHA-256 digest.

### Caller permissions and secrets

Every caller declares job-level permissions explicitly:

```yaml
permissions:
  contents: write
  actions: read # required for cross-run retrieval; Agentic OS grants it unconditionally
```

The contract declares no secrets, and callers never pass `secrets: inherit` to
the contract invocation.
The caller's `GITHUB_TOKEN` remains scoped to the caller repository. A
cross-repository reusable-workflow reference is pinned to a literal 40-character
commit SHA, with the human-readable contract version recorded in a comment. The
installed same-repository Agentic OS caller uses the local workflow path, which
binds it to the caller's own commit.

## Flow

| Step | Guard | Result |
| --- | --- | --- |
| 1. Validate request | Version, tag mode, manifest, and permissions are valid | Invalid requests fail before mutation |
| 2. Read provider state | Resolve tag, release, assets, and ancestry through GitHub APIs | Local ref drift cannot change the decision |
| 3. Reconcile tag | Verify the existing immutable SHA, or create the missing tag in `create` mode | Tag points at `target_sha` |
| 4. Reconcile release | Create a missing release or reuse the existing release | One release per immutable tag |
| 5. Reconcile assets | Upload only manifest entries that are missing | Partial releases are repairable without overwrite |
| 6. Read back | Re-fetch tag, release fields, and the complete manifest | Receipt-backed success |

Concurrency is configured on the contract job inside the reusable workflow,
keyed by repository plus tag, and an in-progress release is never cancelled:

```yaml
jobs:
  contract:
    concurrency:
      group: release-${{ github.repository }}-${{ inputs.tag || format('v{0}', inputs.version) }}
      cancel-in-progress: false
```

Do not key concurrency on `github.workflow`; its value changes when a reusable
workflow is called from different workflows.

## Idempotency and repair

Idempotency is keyed by `(tag, target SHA, asset manifest)`, not merely by release
existence.

| Tag | Release | Assets | Result |
| --- | --- | --- | --- |
| Missing | Missing | — | `create` creates the tag and release; `verify` fails |
| Present at `target_sha` | Missing | — | Create the release at the existing tag |
| Present at `target_sha` | Present | Complete | No-op success; `created=false` |
| Present at `target_sha` | Present | Missing manifest entries | Upload missing assets only; `repaired=true` |
| Present at `target_sha` | Present | Unexpected extras | Fail closed for operator review |
| Present at another SHA | Any | Any | Contract violation; never move the tag |

Assets are additive-only. The contract never deletes or overwrites an existing
asset. A partial release is repaired by rebuilding the exact expected artifact,
rerunning the same tag, and allowing the contract to upload only missing names.
The provider-read size and SHA-256 digest of every present asset must match the
trusted build before a repair begins and after convergence.

### Repair or supersede

Additive repair is allowed only when a retained trusted build was produced from
the exact tagged SHA and the intent is to restore that historical version. A
release is superseded with the next reviewed patch when it must contain any
source change merged after the existing tag, when the original build cannot be
proven, or when its asset identity conflicts with provider state. Never attach
an image digest or any other asset produced from a later commit to an older tag.

The empty `v0.5.6` Agentic OS release has a retained, checksum-valid build from
its immutable tagged SHA, so the contract can repair it additively. That repair
cannot carry later control-plane changes. The governed path for those changes is
a new patch release after they merge and pass the required checks; its release
manifest must read back the newly built immutable control-plane image digest.
The `v0.5.6` tag and release history remain unchanged unless the separate repair
operation is explicitly approved.

## Prereleases and hotfixes

Prereleases are defined as `X.Y.Z-rc.N`, set `prerelease: true`, and are cut only
from the adopting repository's declared `prerelease_ref`, such as a short-lived
`release/*` branch. They are never promoted automatically. This is a defined
future policy, not a currently adopted release lane.

A hotfix starts from the released tag, not from integration. It must merge to
`release_ref` and then back to `integration_ref` when those refs differ. The
release is not closed until both reachability checks pass.

## Required checks

These are provider-read check names as of 2026-07-29. They are bare job names.
Only a reusable workflow call receives a `<caller-job-id> /` prefix.

| Repository role and branch | Required checks |
| --- | --- |
| Agentic OS `main` | `Docs link policy`; `Commit messages`; `Python suite and packaging`; `gui`; `node-services (execution-fabric-control-plane)`; `node-services (execution-fabric-leadership-witness)`; `control-plane-integration`; `deployment-contracts`; `secret-scan` |
| Harness `main` | `validate-and-package` |
| Library `main` | No required checks configured; this is an adoption gap, not permission to bypass validation |
| Brain `main` and `develop` | `test` |

A workflow must not rename a required check accidentally. Protection changes are
separate, explicitly reviewed provider mutations and are never a side effect of
release-contract adoption.

## Manual run and per-repository runbooks

The contract itself has no manual entry point; it is callable only as a reusable
workflow. Use the current adapter trigger and never emulate a release with direct
API writes:

| Repository role | Operator runbook |
| --- | --- |
| Agentic OS | Merge a reviewed version change to `main`; create the intended immutable `vX.Y.Z` tag only after all required checks pass; observe the tag-triggered release; verify all expected assets and image digests. |
| Harness | Merge a reviewed version change to `main`; allow protected CI packaging to finish; the completion event owns release creation. Manual dispatch is only a workflow smoke path and must retain its no-op gate. |
| Library | Merge Conventional Commits to `main`; the repository-local release adapter derives and prepares the next version. Do not add strict protection until its direct-push and skipped-CI behavior has been replaced. |
| Brain | Merge features to `develop`, promote the intended release to `main`, and allow semantic release to run. Verify the manifest-version cross-check before adopting the shared contract. |

After contract adoption, `dry_run: true` is the only manual diagnostic mode. A
dry run performs every provider read and guard, emits the normal outputs, and
creates no tag, release, asset, or branch change.

## Failure handling and rollback

- Version/tag mismatch, ancestry failure, immutable-SHA mismatch, or manifest
  conflict is a contract violation. Exit with code `2`; retrying unchanged input
  cannot repair it.
- Provider timeouts and 5xx responses exit with code `1`; retry is safe because
  the provider state is read again before every mutation.
- A missing caller permission fails closed. Do not add a broad token or inherit
  secrets to make the job pass.
- A missing expected asset is repaired additively. An unexpected asset requires
  operator review; nothing is deleted.
- Roll back one repository by reverting only its caller change. The repository's
  previous build and release path must remain intact until live adoption is proven.

## Receipts and completion

A release is complete only after provider readback proves:

- the tag resolves to `target_sha` and is reachable from `release_ref`;
- exactly one non-draft release exists for the tag;
- the prerelease flag matches the request;
- the expected asset manifest is complete with no unexpected entries;
- every asset name, byte size, and provider SHA-256 digest matches the trusted
  build, including the release manifest that records the control-plane image
  digest;
- repository branch protection is unchanged by the release; and
- repository-local publish targets and provenance receipts are complete.

A workflow dispatch, a created tag, or a successful upload response is not a
completion receipt by itself.

## Recommended defaults and open decisions

Recommended defaults:

- Keep the reusable contract hosted in the public Agentic OS repository.
- Keep Agentic OS in `tag_mode: verify` for the first adoption phase.
- Use shadow `dry_run` adoption before changing any remaining release lane.
- Do not add `develop` to main-only repositories without a staging or beta consumer.

Open product decisions:

- Whether a concrete staging or prerelease consumer justifies creating
  `develop` in any main-only repository.
- Whether a dedicated private workflow host is worth the additional access policy.
- Whether Agentic OS should eventually move from maintainer-created tags to contract-created tags.
- Whether Harness should keep semantic release after shadow validation.

These choices require separate work items and provider mutations. This document
records them; it does not silently decide them.
