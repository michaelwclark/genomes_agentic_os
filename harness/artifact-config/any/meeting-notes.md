---
schema_version: 1
provider: any
artifact_type: meeting-notes
mode: compose
required_sections: [Purpose, Attendees, Decisions, Discussion, Action Items, Open Questions]
format: {renderer: markdown}
approval: {write: explicit}
validation: [actions_have_owner, decisions_are_unambiguous]
---

# Good Meeting Notes

Lead with decisions and actions. Attribute owners and due conditions, separate
discussion from commitment, and avoid unnecessary personal or sensitive detail.
