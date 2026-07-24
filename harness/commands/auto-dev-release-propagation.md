# `/auto-dev-release-propagation`

Compatibility alias for `$auto-dev-pr-create` family mode. Preserve the legacy
command and `release_propagation` recorder state, but emit canonical PR Create
receipts. Delegate every target-resolution decision and provider action to the
PR Create workflow; this command only preserves the compatibility invocation
and receipt.
