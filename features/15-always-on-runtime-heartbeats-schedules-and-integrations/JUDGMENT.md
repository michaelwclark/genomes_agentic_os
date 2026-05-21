# Judgment

The feature is implemented as a file-backed runtime control layer instead of live provider automation.

This is the right boundary for the first runtime pass: it creates registries, validates contracts, writes heartbeat and run-queue evidence, and blocks Notion writes unless the workspace is explicitly verified as Genome's Notion. Orgo.io, Composio, AgentMail, Granola, and Notion are represented with setup tasks, health checks, approval gates, credential environment variable names, and Notion tracking fields without storing secrets.

The remaining production step is to connect real provider execution after the dry-run logs and Notion tracking records are being reviewed consistently.
