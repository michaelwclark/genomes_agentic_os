# Preserve MCP transports during configuration installation

The Codex TOML installer treats an MCP server's transport as one merge decision.
It preserves an existing SSH or other stdio command when the managed template
proposes HTTP, and preserves an existing HTTP URL when the template proposes
stdio. The installer reports the conflict without copying connection values
into that transport-conflict message. It also holds the proposed server's
subtables, so transport-specific settings cannot slip through a separate table.

Run the ordinary config install command in preview mode first. A transport
conflict requires inspecting the named server and deciding which connection
should remain. Confirming configuration conflicts permits other managed
additions; it does not add the competing transport to the preserved server.
Other server tables and unrelated settings continue to use the additive merge.

Same-transport additions remain supported. Existing custom URLs and commands
retain the normal conflict semantics. Mixed transports, duplicate keys or
duplicate server identities in a managed template are rejected before first
installation. Existing ambiguous entries and quoted aliases are preserved with
an actionable conflict instead of creating another table with the same identity.
Unsupported quoted server names are refused rather than guessed.
Inline server definitions, dotted assignments, quoted keys, and other layouts
the additive editor cannot interpret are preserved with a conflict in existing
configuration and refused in managed templates. Other settings still merge.

This repair changes the TOML merge boundary. Claude's separate generated MCP
configuration still follows its existing installer; this repair does not claim
that an installed Claude connection has been migrated. Changing an endpoint,
switching a transport, or validating a real Brain service needs its own explicit
configuration and runtime evidence. Keep secret-bearing configuration and
recovery material in private custody; do not attach them to tracker or PR bodies.

The regression suite uses disposable configurations and the real generated
Codex install/preview/reinstall path. Source and package qualification do not
establish installation on GenomesBox, memory landing, backups, or recovery.
