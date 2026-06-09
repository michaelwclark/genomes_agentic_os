# Remaining Work Review — 2026-06-09

Synthesized from a per-plan acceptance-criteria audit (4 review agents) against the
code, tests, validation results, and git history.

Baseline at review time: 97 pytest tests pass, 55/55 CLI validation commands OK,
uncommitted Composio tool-routing slice in the working tree.

## Plan-by-plan status

| Plan | Verdict | Remaining |
| --- | --- | --- |
| 00–04 | DONE | — |
| 05 customer factory | PARTIAL | No test that validation distinguishes core OS failures from customer profile warnings |
| 06 notion sync | PARTIAL | Live `notion sync --apply` idempotency never validated (F-010) |
| 07 doctor/migrations | DONE | — |
| 08 losmon validation | PARTIAL | "Three real LOS tasks" with run logs never executed (live work) |
| 09 ideas intake | PARTIAL | `os-capture-plan.md` agent guidance file missing |
| 10 notion bootstrap | PARTIAL | Live bootstrap run (Notion IDs recorded back, run in Runs DB) never executed |
| 11 room-first installer | DONE | — |
| 12 factory templates | PARTIAL | Operator-named room generation; factory-content sanitization audit |
| 13 reference/skill index | DONE | — |
| 14 client playbooks | PARTIAL | Brief generation from installed templates; private-identifier audit |
| 15 always-on runtime | PARTIAL | 8 deferred live-install validations (FINAL-VALIDATION.md); integration account setups are manual-by-design |
| 16 source watch registry | PARTIAL | Live adapters (F-013); 9 source example files unconfirmed; 5 deferred live validations |
| 17 event graph | PARTIAL | 6 chain example templates not shipped (`templates/event/` missing); 5 deferred live validations |
| 18 capability registry | PARTIAL | In-flight Composio slice uncommitted; validate/doctor unaware of `composio-tools.yml`; schema unenforced; missing-registry test absent |
| 19 update channel | PARTIAL (policy-gated) | Approval-gate workflow, control-plane status mirror/phone-home send, real additive apply, real rollback restore — deliberately local-first stubs |
| 20 operator updates/backups | PARTIAL | `backup push` subcommand missing (only `backup run`); `fleet push` not started; real GitHub/MCP provisioning still fake-provider-only (gated) |
| 21 harness config.toml | DONE | — |
| 22 work lifecycle/logging | PARTIAL | Hook-failure local log file; stale `building`/finished-undocumented checks in validate/doctor; `test_conversation_logging.py` (synthetic stop payloads + redaction tests); LOS policy fixture; `harness/shared_factory` migration doc note |

## Bucket A — headless code work (orchestratable now)

- **A1** Finish + commit the in-flight Composio slice: validate/doctor awareness of
  `composio-tools.yml`, confirm INVENTORY.md rendering, missing-registry test.
- **A2** F-011: schema enforcement in `validate` (`--strict`, jsonschema over the 22
  `schemas/` files) — also closes plan-18 AC "validation fails when a declared
  capability is missing from its registry."
- **A3** Plan 20 residuals: `backup push` subcommand; `fleet push <customer_slug>`
  operator command against the fake provider.
- **A4** Plan 22 residuals: hook-failure local hook log; stale-work checks;
  `test_conversation_logging.py`; LOS policy fixture; shared_factory migration doc.
- **A5** Plan 05: core-failure vs customer-warning distinction test.
- **A6** Plan 09: `os-capture-plan.md` guidance file.
- **A7** Plans 16/17: ship the 9 connected-source example files and 6 chain-rule
  example templates.
- **A8** Plans 12/14: operator-named room generation, sanitization/private-identifier
  audit, client-automation brief generation.
- **A9** Small backlog: F-003 `doctor --all`, F-012 `metrics refresh`, F-014 routing
  threshold, F-021 friendlier name errors, F-022 `run-log create` discoverability,
  F-020 install ergonomics doc, F-023 DB-plane trigger doc.

## Bucket B — live/credentialed validation (needs Michael present)

- 18 deferred FINAL-VALIDATION items for plans 15/16/17 against `~/agentic_os`
  (Notion track-runtime apply, Granola doctor, live polls, run-due apply).
- F-010 live Notion adapter apply; F-013 live GitHub/Slack adapters + secrets
  contract (code scaffold is orchestratable; live verification needs credentials).
- Plan 08 three real LOS tasks; plan 10 live Notion bootstrap.

## Bucket C — deliberately deferred (policy-gated, do not build yet)

- Plan 19 full update-channel machinery (approval workflow, real apply/rollback,
  phone-home send) — stays local-first until Plan 20 V1 is proven.
- Plan 20 real GitHub/MCP provisioning wiring (fake provider stays until approved).

## Outcome (same day, orchestrated)

Bucket A shipped via 4 subagent branches merged to main: A1 (slice committed +
validate/doctor awareness), A2/F-011 (strict schema validation; fresh installs
strict-clean after remapping skill-registry.schema.json to the distribution
registry and adding skill-visibility-registry.schema.json), A3 (`backup push`,
`fleet push` on the fake provider), A4 (hook-failure log, conversation-logging
tests, LOS fixture, shared_factory docs), A5, A6, A7 (9 source + 6 chain
examples installed), A9 (F-003/F-012/F-014/F-020–F-023). Tests 97 → 195
passed. CLI validation re-run: 55 commands, no defects.

Still open: **A8** (plans 12/14 generation work — needs design input), Bucket B
(live/credentialed validations), Bucket C (policy-gated), F-010, F-013, plus
follow-ups: scaffolder/schema alignment for customer surfaces, doctor
event-on-regression emission, schemas dir resolution for non-editable installs.

## Corrections / notes

- `shared_factory` lives under `harness/shared_factory/` in installs; plan-15 text
  says `shared_factory/05-knowledge/`. Text/implementation alignment item only.
- Backlog statuses are stale: F-001/F-002 (supervisor) and most of F-004 are
  implemented per git history but still listed `todo` — reconcile when touched.
- `tests/test_cli_scaffold.py` is the single shared test file — parallel work must
  put new tests in NEW per-feature test files to avoid merge contention.
