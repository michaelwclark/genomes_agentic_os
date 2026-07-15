# Context migration fixture

This fixture models two legacy workflow objects that copied the same four
context contracts from their domain. CC-303 migrated the committed object
folders to inherit the domain contracts. Tests reconstruct the legacy copies in
temporary space and verify the exact apply, automatic rollback, and restore
paths against this compact after-state.
