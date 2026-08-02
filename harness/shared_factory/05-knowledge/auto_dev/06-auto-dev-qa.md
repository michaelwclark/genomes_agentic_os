# Auto-Dev: QA

Use `/auto-dev-qa` for a standalone, risk-based validation of the behavior being
delivered. QA can run before or after pull-request creation, but it records
evidence against an exact revision, artifact, environment, and policy.

## Inputs

- acceptance scenarios and explicit out-of-scope behavior;
- exact subject revision or built artifact;
- effective `qa_gates`, development, environment, and project policy;
- implementation risk areas, investigation evidence, known regressions, and
  changed migrations/configuration;
- available fixtures, test data, tenants, browsers/devices, and environments.

## Plan and execute

1. Translate acceptance behavior into observable checks, including important
   negative, permission, error, retry, and recovery paths.
2. Select the smallest complete validation set for the risk. Combine focused
   automated tests, integration checks, static/schema checks, and manual or E2E
   behavior only where each adds evidence.
3. Reuse project-owned QA programs, fixtures, test-loan/data factories, and
   environment procedures instead of creating one-off setup.
4. Protect customer and production data. Use approved non-production fixtures
   unless policy and explicit authority permit otherwise.
5. Verify environment, deployed version, tenant/config state, and prerequisites
   before interpreting a result.
6. Record expected versus actual behavior, exact commands/cases, revision,
   environment, data/fixture identity, timestamps, and evidence artifacts.
7. For a failure, determine whether it is a product defect, test defect,
   configuration mismatch, stale version, access problem, or infrastructure
   problem before rerunning or routing work.

Independent QA lanes may be delegated to subagents when they do not mutate the
same fixtures or environment. The coordinator reconciles the results and owns
the final QA judgment.

## Project-owned campaign policy

Ticket-family classification, child QA delivery, fixture/configuration routing,
merge authority, and tracker transitions are project policy. Resolve those
addenda with the other effective policy planes; the shared QA layer only
requires exact-subject evidence and typed outcomes.

## Evidence outcomes

- `passed`: all required checks ran against the intended subject and matched
  expected behavior;
- `failed`: a reproducible mismatch or required quality gate failed;
- `blocked`: required access, environment, fixture, or infrastructure could not
  produce a trustworthy result;
- authorized fallback: project policy explicitly accepts another evidence
  source such as provider CI, with its exact check/job receipt.

Missing access or infrastructure is never rewritten as a passing test. A test
command exiting successfully against the wrong version or environment is also
not passing evidence.

## Done criteria

QA is complete when every applicable gate has a recorded disposition, failures
are routed with reproducible evidence, and the work log explains the tested
scope, result, limitations, and next action. QA does not merge, deploy, or
declare production success.
