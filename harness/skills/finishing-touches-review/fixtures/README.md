# Finishing Touches Review Fixtures

The deterministic helper has a built-in fixture suite that runs when this directory does not provide `fixture-suite.json`.

Current built-in coverage:

- 16 readiness decision cases.
- 7 transition cases.
- 11 external-output scrubber cases.

Run:

```bash
python3 harness/skills/finishing-touches-review/scripts/finishing_touches_review_helper.py fixture-test --fixtures harness/skills/finishing-touches-review/fixtures
```
