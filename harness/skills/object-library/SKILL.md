---
name: object-library
description: Author, build, validate, release, install, and read back reusable Agentic OS Object Library changes through the canonical source repository and existing Auto-Dev stages. Use for Object Library changes, library source/install drift, or requests to publish and install reusable objects.
---

# Object Library

Use this skill for durable changes to reusable Agentic OS programs, workflows,
automations, commands, skills, hooks, rules, references, templates, and
toolkits.

## Procedure

1. Route to the registered `genomes_agentic_lib` source project and the exact
   work item. Read the installed `lib/registry/objects.json` only to select the
   current canonical identity and inspect its manifest/entrypoint.
2. Confirm the authoring checkout belongs to
   `michaelwclark/genomes_agentic_lib`. Do not edit `<os-root>/lib/`; it is a
   disposable installed projection.
3. Use the canonical `library_self_hosting` workflow with the same
   `autodev.json` and normal Auto-Dev predecessor receipts. Do not introduce a
   parallel library lifecycle.
4. Map library work onto the existing stages:

   | Auto-Dev stage | Object Library responsibility |
   | --- | --- |
   | Develop | Change manifests/content and build the deterministic archive plus build receipt. |
   | QA | Validate the exact candidate archive, its manifest/registry identities, and the receipt-bound SHA-256. |
   | Release | Publish the already verified version, tag, archive, build receipt, and changelog. |
   | Deploy | Dry-run, install the immutable released revision into `<os-root>/lib/`, then run install verification and library doctor readback. |
   | Document rerun | After release/deploy, update documentation with the actual version, revision, artifact hash, install receipt, and resume path. |

5. Keep the normal PR Create, Review Self, Review Others, Finalize, Merge,
   Closeout, and Health gates between those responsibilities. Publishing does
   not imply installation, and installation does not imply successful
   readback.
6. Stop before install when the installed projection owns linked Git worktrees
   or uncaptured edits. Preserve and re-home them first. Use
   `--replace-dirty` only for an explicitly receipt-backed one-time migration.
7. Accept Deploy only when `agentic-os library verify-install` proves that the
   installed object count and content hash match the install receipt and
   `agentic-os library doctor` is healthy.
8. Preserve source build/QA/release receipts and runtime install/readback
   receipts outside the installed library. Finish only after post-release
   documentation and the normal Auto-Dev Closeout/Health gates are complete.

## Guardrails

- Every object owns one canonical `object.yml`; generated registries are never
  hand-edited.
- The source version, tag, published archive, build receipt, installed source
  revision, object count, and content hash must agree.
- QA validates the artifact that Release publishes. Release must not silently
  substitute an unverified rebuild.
- Deploy installs an immutable tag or commit whenever one exists, never an
  unverified local working tree.
- Runtime state, logs, receipts, worktrees, caches, backups, secrets, and
  generated execution output remain outside the versioned definition tree.
