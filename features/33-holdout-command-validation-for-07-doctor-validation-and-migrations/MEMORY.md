# Memory

Doctor/migration holdouts should test both repair and refusal paths:
`doctor --fix-missing` restores managed files additively, while migration apply
must refuse missing plans and targets changed after preview.
