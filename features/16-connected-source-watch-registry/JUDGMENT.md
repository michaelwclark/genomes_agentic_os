# Judgment

The feature deliberately stops at local dry-run and local event-write behavior. That satisfies the registry contract while avoiding unverified external reads or provider-specific code.

Provider adapters can now be added behind the normalized source-event shape without changing downstream routing or chain-processing contracts.
