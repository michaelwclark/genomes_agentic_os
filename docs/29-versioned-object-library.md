# Versioned Installed Object Library

The installed Agentic OS keeps operator-specific reusable definitions in a
dedicated Git repository at <os-root>/lib. This avoids mixing private LOS,
consulting, and personal definitions into the generic genomes_agentic_os source
package.

## Layout

    lib/
      programs/
        root/<program>/
        domains/<domain>/<program>/
        domains/<domain>/projects/<project>/<program>/
      hooks/
      workflows/
      automations/
      commands/
      skills/
      rules/
      references/
      templates/
      toolkits/
      registry/
        objects.json
        programs.yml
        hooks.yml
        workflows.yml
        automations.yml
        commands.yml
        skills.yml
        rules.yml

Every object owns object.yml. Its stable identity includes kind and scope, for
example program:root:development_delivery or
automation:project:los:los_app_los_django:pr_health.

Manifests are canonical for mutation. registry/objects.json is the compact
canonical read projection used by agents; per-type YAML registries are generated
human-readable projections. Generated registries are never edited directly.

## Operations

    agentic-os library init --root ~/agentic_os --git --apply
    agentic-os library migrate-legacy --root ~/agentic_os
    agentic-os library migrate-legacy --root ~/agentic_os --apply
    agentic-os library refresh --root ~/agentic_os --apply
    agentic-os library list --root ~/agentic_os --kind program
    agentic-os library show program:root:development_delivery
    agentic-os library doctor --root ~/agentic_os

Migration is copy-first. Runtime outputs, logs, caches, receipts, state,
worktrees, large generated files, and secret-shaped files are excluded from the
versioned definition copy. Compatibility paths remain until callers and writers
have moved to the library resolver.

During cutover, manifests retain `runtime.legacy_roots` for existing run, log,
state, and artifact directories while `runtime.root` names the new canonical
destination. Runtime data moves only after its writer changes and parity checks
pass; it is never pulled into the definition repository.

Durable domain reference documents migrate from ungoverned `05-knowledge`
folders into scoped `reference` objects. This preserves real LOS and consulting
material while allowing empty/default knowledge scaffolds to be removed.

## State Is Not An Object Definition

`lib/` versions reusable definitions. Mutable current-work truth stays in
`harness/shared_factory/00-control-plane/state.db`. The `work_items` table stores
canonical lifecycle state and an independent attention value: `active`,
`queued`, `parked`, or `closed`. This prevents a large backlog from becoming
implicit active context.

Agents read `harness/shared_factory/00-control-plane/active-now.json` first and
use `agentic-os work list/show` for detail. They update truth with
`agentic-os work upsert/set`; each transition is recorded in
`work_item_history`. Packet paths are stable under
`domains/<domain>/projects/<project>/work-items/<id>/` and never move merely
because state changes.
