# Object Library Self-Hosting

## Outcome

A reusable-object change is authored in the normal Object Library source
repository, built and validated as one exact artifact, published immutably,
installed as a replaceable Agentic OS projection, read back, and documented
without creating a second SDLC.

## Topology

| Surface | Responsibility |
| --- | --- |
| `genomes_agentic_os` source package | Owns the installer, resolver, compatibility adapters, and this Auto-Dev workflow. |
| `michaelwclark/genomes_agentic_lib` | Owns durable reusable definitions, manifests, generated registries, versions, release archives, and changelog. |
| `<os-root>/lib/` | Read-only-in-practice installed projection of one validated source revision. |
| `<os-root>/runtime/` and the work-item packet | Own install receipts, backups, stage evidence, logs, and resume state. |

Compatibility command, skill, workflow, and numbered-folder paths may route to
these objects. They do not become additional definition owners.

## Existing Auto-Dev stage mapping

This workflow is a reusable profile over the canonical stage order. It does
not add Build, Validate, Publish, Install, or Post-Release Documentation stages.

| Existing stage | Library action | Required proof |
| --- | --- | --- |
| Develop | Edit source manifests/content and build the deterministic archive. | Archive name/version, file/object counts, source revision/tree hash, archive SHA-256, and build receipt. |
| QA | Validate the exact candidate archive and receipt, including every object identity, entrypoint, registry row, symlink boundary, and forbidden runtime/secret-shaped path. | QA receipt bound to the archive SHA-256 that Release will publish. |
| Release | Publish the verified tag, archive, build receipt, and changelog through protected release authority. | Provider readback proving the immutable version and artifact hash. |
| Deploy | Plan and atomically install the released tag or commit, then run `library verify-install` and `library doctor`. | Install receipt plus installed object-count/content-hash readback. |
| Document rerun | Refresh the same documentation workflow after Release and Deploy. | Docs/changelog name the actual version, source revision, published hash, installed result, and resume path. |

The first Document pass still occurs in its normal pre-PR position. The
post-release pass is a rerun of the same workflow and adds a linked receipt; it
does not insert or reorder an Auto-Dev stage.

## Inputs

- canonical object identity and source manifest;
- registered source repository and clean branch/worktree;
- source `VERSION`, changelog, build/validation commands, and release policy;
- target Agentic OS root and immutable tag or commit for installation;
- normal Auto-Dev work item, policy fingerprint, approval, provider, and
  predecessor receipts.

## Steps

1. Read the installed compact registry to identify the object, then resolve the
   matching source object. Never start authoring from the compatibility alias.
2. Run Auto-Dev Readiness for repository, branch, version, release target,
   target OS root, and source/install boundary.
3. Run Develop to change manifests/content and create the deterministic archive
   plus build receipt.
4. Run normal PR creation and review gates. Run QA against the exact candidate
   archive and freeze its hash in the evidence used by Release.
5. After governed merge, run Release. The published archive and provider
   readback must match the QA-bound version and hash.
6. Run Deploy dry-run first. Stop if installed `lib/` has linked worktrees or
   uncaptured changes. On approved apply, stage, validate, atomically replace,
   and read back the exact released revision.
7. Rerun Document to record actual publication and installation truth. Then
   proceed through the normal Closeout and Health owners.

## Failure and recovery

- **Source or manifest invalid:** remain in Develop; repair the source object
  and rebuild before QA.
- **Candidate hash changes after QA:** invalidate QA and repeat it against the
  new archive; do not publish the replacement under the old evidence.
- **Release provider unavailable or tag/version mismatch:** pause Release with
  the exact owner action; do not install a local substitute.
- **Installed projection dirty or owns linked worktrees:** block Deploy, capture
  the edits in source or re-home the worktrees, and rerun the dry-run.
- **Staged validation or atomic replacement fails:** retain the previous
  installed projection and the failure/backup receipt; repair the source or
  installer and resume Deploy.
- **Install readback differs:** Deploy is incomplete. Preserve the receipt and
  backup, repair or roll back, then rerun verification.

## Completion

Completion requires source review/merge proof, exact-artifact QA, immutable
release readback, install and doctor readback, post-release documentation, and
the ordinary Auto-Dev Closeout/Health receipts. A local build, merged source,
published release, or successful copy alone is not completion.
