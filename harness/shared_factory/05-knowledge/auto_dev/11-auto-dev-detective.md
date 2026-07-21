# Auto-Dev: detective

Use `/auto-dev-detective` for bugs, QA failures, ticket comments, logs, alerts,
incidents, suspicious behavior, and root-cause questions. Detective is an
evidence-led, read-only workflow. It can run before grooming, during delivery,
or after a regression without silently becoming implementation.

## Normalize the question

Identify the observed behavior, expected behavior, reporter/source, time range,
environment, tenant/account scope, severity, reproducibility, known changes,
and the decision the investigation must support. Separate a symptom from a
claimed cause.

## Evidence order

1. Resolve and receipt the exact deployed tag/SHA/version for any
   environment-scoped code claim.
2. Read the live tracker and existing work-item evidence.
3. Prefer valid local/cached configuration, rules, history, and indexed evidence
   when project policy says it is authoritative enough.
4. Use source and tests at the deployed revision, not the default branch, when
   explaining named-environment behavior.
5. Make bounded live reads for stale, missing, runtime-only, observability, or
   mutation-gating facts.
6. Record every source, query/command summary, timestamp, version boundary, and
   redaction in the investigation packet.

Use parallel subagents for independent hypotheses or evidence systems, not for
duplicated broad searching. The coordinator maintains the evidence map and
checks that conclusions cite actual recorded evidence.

## Analysis method

- state testable hypotheses and predicted observations;
- seek disconfirming evidence, not only confirmation;
- distinguish root cause, contributing condition, trigger, and unrelated noise;
- explain confidence and what would change the conclusion;
- identify the smallest next discriminating check when evidence is incomplete;
- keep secrets and customer data out of reports and logs.

When VPN, environment, provider, authentication, or another source is
unavailable, record its explicit disposition and pause the same investigation.
Resume only after fresh availability evidence. Do not create repeated failed
runs or conclude from absence that could not be verified.

## Outputs and done criteria

Produce an evidence-backed investigation report or RCA through Create
Artifacts. It includes facts, hypotheses considered, disconfirming evidence,
conclusion or current best explanation, confidence, impact, remediation options,
and next action.

Detective completes when the question is answered at the requested confidence
or the exact missing evidence and discriminating next check are explicit. It
does not change code, configuration, environments, or tracker state without a
separately authorized workflow.
