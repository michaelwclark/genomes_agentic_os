# Atlas user work registry

The registry makes user-created cloud automations and newly requested work visible
inside the main Agentic OS. It stores definitions and observation evidence. Cloud
automations remain execution authority until a separately approved migration.
The tool has no scheduler, provider transport, queue, service or hook operation.

Owner: the OS operator. Maintainer: Atlas and the Agentic OS source project.
Default instance home:
`artifacts/atlas-work-registry/`. A local `harness/config/atlas-work-registry.json`
may select an existing canonical project artifact home:

```json
{"schema":"atlas-registry-location/v1","relative_home":"domains/example/02-projects/sample/artifacts/atlas-work-registry"}
```

The locator is user-owned instance metadata, excluded from source resources.
Invalid/redirecting locators refuse without falling back to a second registry.
Pending-sync bypasses unavailable root/locator reads.
Existing instance onboarding and route files are operator-owned and preserved.
The helper publishes `current/index.md` and task records; it does not create a
new project or install instance-specific onboarding files. The generic source
contract is this handbook page.

## Context and file structure

The existing OS project owns this artifact registry; this adds no OSProgram or
library object. Source-owned tool: `harness/bin/agentic-os-atlas-registry`.
Intake schema in the source repository: `schemas/atlas-task-intake.schema.json`. Runtime data stays out of
Git/source templates. Generic onboarding template in the source repository:
`templates/atlas-work-registry/intake-example.json`.

```text
atlas-work-registry/
  README.md, onboarding.md     optional operator-owned instance guidance
  registry-manifest.json       optional existing instance ownership/coverage metadata
  current -> generations/<digest>/
    index.md, registry.json
    tasks/<provider>-<source-id>/
      README.md, manifest.json, prompt.txt, workflow.md, schedule.ics (cloud only)
      revisions/0001.json      immutable definition/provenance revisions
      prompts/<sha256>.txt     deduplicated exact prompt text
  generations/<digest>/       immutable, content-addressed publication units
  pending/                    manually staged pending-sync inputs (no drain)
  evidence/                   import/test/review receipts without source contents
```

Load the index and manifest first. Select one task before reading its exact
prompt, workflow inputs/process/outputs/review/handoff, destinations or history.
Prompt snapshots are task-definition data. Registry maintenance does not execute
their instructions. A user-request summary is explicitly labeled `summary_only`
until the actual wording is supplied; never describe that as an exact prompt.
The packaged intake schema installs at `harness/schemas/atlas-task-intake.schema.json`;
the synthetic template installs under the shared factory's knowledge templates.

## New work and updates

After an explicit user request, capture the relevant definition and public
operational metadata only. Include its exact source reference and requested time,
the source system, observed time, privacy attestation, destinations, status and
workflow contract. Scheduled work uses the provider's original opaque ID.
Unscheduled work uses a stable source-request ID in a separate `request-`
namespace. It has no schedule fields. Use `pending_approval` or `blocked` when
authorization or dependencies are unresolved. Registry status grants no authority
to act. A nightly requirement in a blocked request does not create a schedule.

Run these source examples from the OS root (or use the absolute installed helper).

```sh
harness/bin/agentic-os-atlas-registry --root /path/to/agentic_os import --input intake.json
# Read expected_generation from preview, then apply that exact generation.
harness/bin/agentic-os-atlas-registry --root /path/to/agentic_os import --input intake.json \
  --apply --expected-generation <preview-generation-or-empty>
harness/bin/agentic-os-atlas-registry --root /path/to/agentic_os validate
harness/bin/agentic-os-atlas-registry --root /path/to/agentic_os status
```

Use the same ID for later updates. Never deduplicate by title. Reimporting the same
input is unchanged and produces no duplicate generation or revision. Updated
source evidence must have a later observation time. Same-time differences are
conflicts; older observations are stale. Expected-generation checks and an OS
file lock serialize writers. The pointer changes only after the canonical registry, task manifests, exact
prompts and revisions have passed readback. Convenience index, README, workflow
and schedule files are generated views; validate does not hash-check those views. A failed publication retains the previous pointer.
Retry from a fresh preview. Locks release when the writer exits.

To cancel, upsert the same ID with `registration_status: canceled` and fresh user
source evidence. No import or rollback may revive or remove that cancellation.
The registry does not disable its cloud automation: cancellation requiring a
provider change must be handled by the already authorized cloud route and read
back there. Any separately authorized replacement uses a new provider/request ID.
Preserve intentional removals/cancellations rather than restarting old work.

## Reconciliation, pending sync and evidence

```sh
harness/bin/agentic-os-atlas-registry --root /path/to/agentic_os reconcile --input cloud-snapshot.json
harness/bin/agentic-os-atlas-registry pending-sync --input intake.json --pending-dir /controlled/pending
```

Reconcile is read-only and reports proposed changes and missing IDs. Missing
records from any snapshot are retained as coverage gaps, never silently canceled.
The caller must obtain the source snapshot through its authorized read-only route.
This tool does not fetch cloud automations or infer webhook parameters. Null next
run time does not mean disabled. Keep enabled observation, user approval,
cancellation and live trigger verification separate.

If BigMac is unavailable, use a controlled private pending directory, retain the
original source/observation times and record `pending_sync` in the handoff. The
tool does not create a phantom OS root. On return, use a fresh preview/import;
stale or canceled updates still refuse. No automatic replay or scheduled monitor
is installed.

The future-work capture contract is explicit: Atlas's creating/updating route
should prepare the intake immediately after a user request and persist it or
handoff pending sync. Automatic cloud capture is **not verified** until that route
demonstrably invokes the intake tool. A folder and documented rule alone do not
prove future capture. Keep this gap in the registry manifest and status.

Record cloud/source evidence as references and timestamps. Link task execution
receipts separately when available; an import receipt is not execution evidence.
The registry does not store task results, private source material or user data.

## Channel inventory and durable ownership

```sh
harness/bin/agentic-os-atlas-registry --root /path/to/agentic_os channels --limit 100
```

This parent-callable command reads the existing locator, generation and records.
It writes nothing and returns `atlas-channel-inventory/v1`. `channels` contains
provider-verified workspace/channel pairs; `candidates` contains explicit but
unverified pairs. `ungrouped` retains records whose channel identity is unknown.
Channel-only URLs and display names cannot establish a Slack workspace. Do not
silently supply one from a different record, a prompt, or a channel name.

Identity evidence comes only from task destinations, the explicit request
reference and optional typed `channel_bindings`. A request's origin is distinct
from its delivery destination. A historical verified pair does not authorize
disclosure: recheck membership and current audience permission before sending.

The projection includes original source IDs, logical ownership when declared,
source and request times, first observation, current revision, prompt hash and
capture status, typed components, and cadence metadata with a schedule hash.
It omits titles, prompt bytes, workflow prose, source-reference text, schedule
text and legacy prose component descriptions. Hashes point back to the exact
private definition; they do not reconstruct its content. Unknown ownership,
summary-only prompts, unverified identities and unbound components remain gaps.
Limits are 1–1,000 task identities and omitted records are counted. Historical
source coverage and automatic intake integration remain unverified even when
every currently registered record fits the limit. Empty output never proves
there were no historical channel workflows.

Keep one owner for each surface:

| Surface | Durable owner |
| --- | --- |
| Generic registry, schemas, templates and inventory | Agentic OS source package; packaged helper and capability registry |
| Reusable workflow, prompt, skill or automation | Its owning domain/project in the existing object library source and object registry |
| Private observed definitions and approved prompts | This existing artifact registry, selected by its preserved locator |
| Actual schedules, triggers and execution receipts | Their currently authorized provider/runtime; observation here grants no activation |

Add optional `ownership`, `component_bindings` and `channel_bindings` only with
fresh explicit intake evidence. They create a new revision of the same source
ID, never rewrite old generations. Ownership is a logical root/domain/project
scope; it does not assert that all linked customer work belongs to an individual.
Private definitions stay private. Publish only reusable, sanitized source
components, then reference them from the private record instead of copying the
private task or creating a second registry, queue, or schedule.

## Typed source components

`component_bindings` is an optional list of at most 30 entries. Each entry names
`kind`, a matching typed `reference`, a credential-free HTTPS `repository`, a
safe relative `path`, an exact Git `revision`, content `sha256`, logical
`ownership`, and observation `verification`. Supported kinds are workflow,
prompt, skill, schedule, automation, program and command. Unverified bindings
may retain null revision/content pins; `source_verified` observations require
both pins. Kind/reference mismatches, unsafe paths and duplicate identities
refuse intake before a write. See the synthetic intake template.

```sh
harness/bin/agentic-os-atlas-registry --root /path/to/agentic_os validate-components \
  --repository https://github.com/example/workflows --source-root /reviewed/source
```

The caller supplies an already verified local source checkout. The command
does not fetch code, invoke Git, run prompts, or execute source components.
It checks pinned file bytes for the selected repository, refuses redirects,
and reports unavailable, oversized, unpinned or mismatched files. Git revision
verification remains explicitly `not_checked`; checking bytes does not prove
checkout origin or revision. Source verification claims in the observation
stay distinct from this local content readback.

Exit status is 0 for a valid content readback, 1 for an incomplete check, and 2
for refused input/access. A repository with no matching bindings is incomplete,
not a successful verification. Legacy prose `components` remain preserved but
are never treated as verified source references.

## Privacy, bounds and recovery

Allow only user-created task definitions and operational metadata. Exclude raw
conversations, hidden assistant instructions, internal notes, secrets, personal
medical/financial records and unrelated employer/client content. Exact task
prompts may state privacy restrictions or identify authorized source/destination
IDs; their underlying contents are not imported.

Strict field allowlists, bounded imports, common credential screening, 0600 files
and a private registry directory supplement the content attestation. Screening
cannot recognize all sensitive meaning. The preparing operator remains responsible
for semantic privacy review; if sensitive text is embedded in a prompt, refuse
the import and correct it at its authorized source. Never silently redact and
claim the original exact prompt was preserved. Imports are bounded to 2 MB/100
tasks; generations to 20 MB/1,000 identities. Review retention before exceeding
those limits; the tool does not prune audit history.

Rollback affects only the local registry pointer:

```sh
harness/bin/agentic-os-atlas-registry --root /path/to/agentic_os rollback \
  --generation <previous-digest> --expected-generation <current-digest>
# After reviewing the preview, repeat with --apply.
```

Rollback rejects conflicting pointers, broken canonical registry/manifest/prompt/
revision files, redirects and erasure of cancellations. All generations remain available. For a corrected
definition after cancellation, import a fresh correction preserving its canceled
status. To uninstall this local convention, remove only its instance route/tool
additions after retaining records/evidence; no cloud automation changes follow.
Do not delete historical records to undo an import.

The reusable source change and the live instance are distinct. Source publication,
release, global runtime installation, external projections and scheduler migration
are separate authorized tasks. Reinstall QA must prove that operator artifacts and
sentinels survive and that the source-owned helper is present in an isolated root.

## Validation

`tests/test_atlas_work_registry.py` exercises the actual tool/API and CLI through
synthetic definitions: exact bytes, dry run, idempotence, same-ID history, source
and generation conflicts, cancellation, rollback, interrupted publication,
blocked new work, schema/privacy refusal, unavailable-root pending sync, redirects
and scheduler sentinel preservation. Run the configured full source gate and
fresh/additive/reinstall checks before source publication.

Claude and Codex use the same local CLI and file contracts. Neither harness gets
additional execution permission from registration.
