# Work Item Templates

These templates define the canonical project work-item packet used after a spec
is promoted out of intake.

Default project spec intake is intentionally lighter:

`work-items/01-intake/001_idea_slug.md`

When the spec is solidified, duel-reviewed, or ready for implementation, it can
expand to an intake packet at `work-items/01-intake/001_idea_slug/` or move to
an active packet under `work-items/001_idea_slug/` using these
templates. Generated subtasks keep the parent index, for example
`001_01_update_database.md`. Completed work moves to `work-items/03-complete/`.

New packets use `SPEC.md` as the raw-capture plus refined-spec file. `IDEA.md`
is a legacy compatibility template for existing packets only.
