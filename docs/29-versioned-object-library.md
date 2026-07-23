# Versioned Object Library

> **Outcome:** reusable Agentic OS objects have one durable source repository,
> one validated release artifact, and any number of receipt-backed installed
> projections. An edit inside installed `lib/` is never mistaken for source.

## The topology in plain English

| Surface | Owns | Must not own |
| --- | --- | --- |
| `genomes_agentic_os` source package | Object Library resolver/installer code, bootstrap scaffolding, Auto-Dev self-hosting workflow, and compatibility adapters. | Operator-specific reusable definitions or installed runtime state. |
| `michaelwclark/genomes_agentic_lib` | Canonical `object.yml` definitions, entrypoints/supporting content, generated registries, version, changelog, deterministic archives, and release automation. | Work items, run logs, install receipts, secrets, or installed-only edits. |
| `<os-root>/lib/` | A validated, replaceable projection of one source revision for fast local routing and inspection. | Durable authorship, linked development worktrees, mutable runtime output, or its own release history. |
| `<os-root>/runtime/` and the active work-item packet | Install receipts/backups, Auto-Dev stage evidence, failure details, and resume state. | Reusable definition truth. |
| Numbered folders and legacy aliases | Stable compatibility/read routes to canonical object identities. | A second writer or policy owner. |

The boundary is deliberate: the generic package can improve the machinery,
the library source can version private reusable knowledge normally, and an
installed OS can replace `lib/` without losing authorship or runtime history.

## Two update lanes

There are two independent things to update:

1. The **Agentic OS package/installer** updates the Python machinery,
   scaffolding, schemas, commands, and installer implementation. After that
   package is installed, `agentic-os update plan` and `agentic-os update apply`
   reconcile its bundled operating surfaces into the selected OS root.
2. The **Object Library installer** updates reusable definitions by fetching a
   chosen `genomes_agentic_lib` tag or commit, validating it in staging, and
   atomically replacing `<os-root>/lib/`.

Updating one does not silently update the other. This keeps an OS code release
from changing private definitions and keeps a library release from replacing
the OS runtime. A future convenience wrapper may select the newest approved
library tag, but it must still call the same dry-run-first install transaction.
Never run `git pull` inside installed `lib/`; there is intentionally no Git
checkout there after migration.

## Object identity and layout

Objects are grouped by kind and scope:

```text
programs|workflows|automations|commands|skills|hooks|rules|references|templates|toolkits/
├── root/<object>/
└── domains/<domain>/
    ├── <object>/
    └── projects/<project>/<object>/
```

Every object owns `object.yml`. Its stable identity combines kind and scope,
for example `program:root:auto-dev` or
`workflow:project:los:los_app_los_django:release-check`. The manifest declares
the entrypoint, owner, dependencies, aliases, runtime boundary, and validation.

`registry/objects.json` is the compact generated read index. Per-kind YAML
registries are generated human-readable projections. Regenerate them from
manifests; never hand-edit a registry to change an object.

## Read installed objects, author source objects

Agents start with the installed compact registry:

```bash
agentic-os library list --root <os-root>
agentic-os library show <canonical-object-id> --root <os-root>
```

That read identifies the current object. A durable change then moves to a
branch or worktree of the registered `genomes_agentic_lib` source project. Edit
the source manifest and entrypoint there. Do not keep working in the installed
path merely because an alias made it easy to find.

## Self-hosting uses existing Auto-Dev stages

The `object-library` skill and `library_self_hosting` workflow are a profile
over Auto-Dev, not a second lifecycle.

| Existing Auto-Dev stage | Object Library meaning | Done evidence |
| --- | --- | --- |
| Develop | Change source objects and build a deterministic versioned archive plus JSON receipt. | Source revision/tree hash, version, file/object counts, archive SHA-256, and build receipt agree. |
| QA | Validate the exact candidate archive, including manifests, entrypoints, canonical identities, registries, symlinks, and forbidden runtime/secret-shaped paths. | QA evidence is bound to the SHA-256 that Release will publish. |
| Release | Publish the verified tag, archive, build receipt, and changelog through protected authority. | Provider readback proves version, revision, and artifact hash. |
| Deploy | Dry-run and atomically install the immutable released revision; run install verification and library doctor. | Installed revision, object count, and content hash match the install receipt. |
| Document rerun | Refresh docs after Release and Deploy. | Changelog/operator docs name actual version, revision, published hash, installed result, and resume path. |

The first Document pass remains before PR Create in the normal Auto-Dev order.
The post-release update reruns the same Document workflow and adds linked
evidence; it does not create or reorder a stage. Normal PR Create, reviews,
Finalize, Merge, Closeout, and Health still apply.

The command/skill pair exposes thin source helpers without becoming another
state machine:

```bash
agentic-os library build --source-root <library-source> --require-clean --require-revision
agentic-os library validate --source-root <library-source> --receipt <build-receipt>
agentic-os library release --source-root <library-source>
agentic-os library document --source-root <library-source> --input <provider-readback> --required-asset <name>
```

`release` prepares evidence and release notes; protected CI or an authorized
operator still performs publication. `document` verifies provider readback and
post-release documentation; it does not publish.

## Install and verify an immutable revision

Installation is dry-run-first. Prefer a release tag or commit:

```bash
agentic-os library install --root <os-root> --repository <git-url> --ref <tag-or-commit>
agentic-os library install --root <os-root> --repository <git-url> --ref <tag-or-commit> --apply
agentic-os library verify-install --root <os-root>
agentic-os library doctor --root <os-root>
agentic-os library rollback-install --root <os-root>
agentic-os library rollback-install --root <os-root> --apply
```

Managed hosts may set `AGENTIC_OS_LIBRARY_REPOSITORY`. The generic product does
not hard-code one operator's source repository.

Apply holds one install-wide lock, clones into a staging directory, checks out
the exact revision, validates the complete projection and every generated
registry, runs any standalone library validator, strips source Git metadata,
and atomically swaps `lib/`. A durable journal either completes or reverses an
interrupted swap. The previous install and its matching receipt are retained
as one rollback generation when the prior target was already receipt-backed.

The current durable receipt is `runtime/state/library-install.json`; historical
install receipts and backups live under runtime-owned paths outside `lib/`.
`verify-install` compares the receipt with live object count/content hash and a
healthy library doctor result. `rollback-install` is dry-run-first and restores
the retained projection and receipt as one verified transaction.

## Fail-closed replacement rules

Installation stops before replacement when:

- installed `lib/` owns linked Git worktrees;
- it contains uncaptured changes and no explicit migration override exists;
- staged source cannot resolve the requested tag/commit;
- manifest, registry, standalone validation, or staged doctor fails; or
- installed readback differs from staged validation.

Re-home linked worktrees and preserve useful installed edits in the source
repository before retrying. `--replace-dirty` exists only for an explicit,
receipt-backed one-time migration after those edits have been captured. It is
not a normal update flag.

On a failed swap/readback, preserve the failure and backup receipts and restore
the prior projection. Never repair by hand-editing generated registries or by
claiming that a successful copy proves a correct install.

## Bootstrap and legacy migration

`library init`, `library create`, `library migrate-legacy`, and
`library refresh` remain bootstrap/migration tools. Plan before `--apply`.
Their output is not durable until the resulting definitions and generated
registries are reviewed in the source repository.

Legacy numbered folders may remain as compatibility aliases while readers and
writers migrate. Runtime directories referenced by old objects remain outside
the source definition and may be named under `runtime.legacy_roots`; they are
not copied into the versioned object.

## Validation checklist

- Every source object has a valid manifest and existing entrypoint.
- Canonical identities are unique and every dependency resolves.
- Generated registries match manifests exactly.
- Runtime, secret-shaped, unsafe symlink, and mutable output paths are absent.
- The build receipt matches the deterministic archive.
- QA, release readback, install receipt, and installed readback name the same
  version/revision/artifact chain.
- Command (`agentic-os library`), skill (`object-library`), workflow
  (`library_self_hosting`), program components, and manifests stay in parity.
