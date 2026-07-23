# `/auto-dev-detective`

Use this command implicitly for reported bugs, failed QA, ticket comments, log
entries, alerts, incidents, suspected causes, RCA work, or questions such as
“why does this happen only for this tenant/environment?”

1. Route to the domain/project and normalize the signal.
2. Resolve the effective investigation plan and source catalog.
3. Start or resume one receipt-backed run.
4. For environment work, resolve the exact deployed version before code
   analysis.
5. Gather bounded read-only evidence from the declared sources.
6. Pause the same run once when VPN/provider/environment access is unavailable.
7. Compare hypotheses, contradictions, and disconfirming evidence.
8. Conclude with confidence and gaps, then render through Create Artifacts.

```bash
agentic-os detective resolve --trigger <trigger> --domain <domain> \
  --project <project> --environment <env> --explain
agentic-os detective start --input <signal.yml> --trigger <trigger> \
  --domain <domain> --project <project> --environment <env> --tenant <tenant>
agentic-os detective record-version --run-dir <run> \
  --authority-receipt <investigation-version-authority.json>
agentic-os detective record-evidence --run-dir <run> --source <source-id> \
  --summary <summary> --fact <fact> --limitation <limitation> \
  --authority <policy-authority-class> --evidence-ref <safe-ref>
agentic-os detective source-status --run-dir <run> --source <source-id> \
  --status <not-applicable|unavailable|deferred> --reason <reason> \
  --evidence-ref <safe-ref>
agentic-os detective conclude --run-dir <run> --analysis <analysis.yml>
agentic-os detective render --run-dir <run> --provider <provider> \
  --type <investigation-report|root-cause-analysis>
```

Investigation is read-only. A conclusion does not authorize a fix, deployment,
configuration/data mutation, or external artifact write.

The version receipt must use `investigation-version-authority/v1`, match the
run's environment, tenant, source, and policy authority class, and contain the
verified version plus evidence reference and timestamp. Resume requires a
matching `investigation-availability/v1` receipt; arbitrary evidence strings do
not reopen a paused run. Conclusions cite recorded evidence IDs and require all
planned sources to be completed or explicitly resolved.
