# Object Library

Use `agentic-os library` to read or install the reusable Agentic OS Object
Library. Durable authoring happens in the normal
`michaelwclark/genomes_agentic_lib` source repository. The installed
`<os-root>/lib/` directory is a validated, replaceable projection and is never
the normal place to edit an object.

## Read the installed projection

Read the compact registry before opening individual definitions:

```bash
agentic-os library list --root <os-root>
agentic-os library list --root <os-root> --kind skill
agentic-os library show skill:root:object-library --root <os-root>
agentic-os library doctor --root <os-root>
```

`library show` resolves one canonical identity such as
`program:root:auto-dev` or
`workflow:project:los:los_app_los_django:release-check`. Open only the
returned `object.yml` and entrypoint when inspecting an installed object.

## Author in the source repository

Normal changes use a branch or worktree of the Object Library source project:

1. Select the canonical object from the installed registry.
2. Change the matching source `object.yml` and its declared entrypoint.
3. Run the repository build through Auto-Dev Develop.
4. Run Auto-Dev QA against the exact archive and build receipt.
5. Merge and publish that verified revision through Auto-Dev Release.
6. Install and read back the published revision through Auto-Dev Deploy.
7. Rerun Auto-Dev Document so the changelog and operator docs name the actual
   released version, source revision, and install result.

Use the `object-library` skill and `library_self_hosting` workflow for the full
contract. They reuse existing Auto-Dev stages; they do not create separate
Build, Validate, Publish, Install, or Documentation state machines.

The following thin command adapters invoke source-owned helpers while leaving
stage state and authority with Auto-Dev:

```bash
agentic-os library build --source-root <library-source> --require-clean --require-revision
agentic-os library validate --source-root <library-source> --receipt <build-receipt>
agentic-os library release --source-root <library-source>
agentic-os library document --source-root <library-source> --input <provider-readback> --required-asset <name>
```

`library release` only prepares release evidence and notes; protected CI or an
authorized operator still publishes. `library document` verifies release
readback and documentation evidence; it does not publish.

## Install an exact source revision

Install is dry-run-first. Prefer an immutable release tag or commit over a
moving branch:

```bash
agentic-os library install --root <os-root> --repository <git-url> --ref <tag-or-commit>
agentic-os library install --root <os-root> --repository <git-url> --ref <tag-or-commit> --apply
agentic-os library verify-install --root <os-root>
agentic-os library doctor --root <os-root>
agentic-os library rollback-install --root <os-root>
agentic-os library rollback-install --root <os-root> --apply
```

`AGENTIC_OS_LIBRARY_REPOSITORY` may supply the same source URL for a managed
host. There is no product-wide personal repository default.

The apply path runs under a single install lock, clones into staging, validates
the complete projection and every registry, removes source Git metadata,
atomically replaces `lib/`, and reads the installed content back. An
interruption journal restores or finalizes the transaction on the next apply.
The durable current receipt is
`runtime/state/library-install.json`; historical install receipts and backups
remain outside `lib/` under the runtime tree.

When the previous generation was already receipt-backed, `rollback-install`
restores that exact projection and matching receipt together. It is also
dry-run-first; use `--apply` only after inspecting the planned revision and
hashes.

Installation stops before replacement when the installed copy has linked Git
worktrees or uncaptured changes. `--replace-dirty` is a one-time,
receipt-backed migration override after those changes have been preserved in
the source repository; it is not a normal update flag.

## Bootstrap and migration commands

These commands support initial construction and legacy cutover. They are not a
reason to resume ordinary authoring inside installed `lib/`:

```bash
agentic-os library init --root <os-root>
agentic-os library create <kind> <id> --root <os-root> [scope options]
agentic-os library migrate-legacy --root <os-root>
agentic-os library refresh --root <os-root> --apply
```

Plan before `--apply`, preserve the migration receipt, and move the resulting
definition into the source repository before treating it as durable. Generated
files under `registry/` are read projections; never hand-edit them.

Runtime logs, runs, work items, state, caches, receipts, backups, artifacts,
secrets, and worktrees do not belong in an object definition repository.
