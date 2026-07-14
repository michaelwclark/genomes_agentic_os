# OS New Feature

Compatibility commands: `/new-feature`, `/add-feature`, `/new-idea`

These are typed adapters for `/add-spec`, not separate feature or idea intake
workflows.

| Alias | Canonical operation |
| --- | --- |
| `/new-feature` | `/add-spec --type feature` |
| `/add-feature` | `/add-spec --type feature` |
| `/new-idea` | `/add-spec --type feature --status idea` |

Follow `harness/commands/os-add-spec.md` and the `spec-engine` skill. New work
must use the canonical Spec statuses and one configured filesystem, Linear, or
Jira adapter. Existing `IDEA.md` and older feature packets remain readable
migration inputs; do not create them for new work.
