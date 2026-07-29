# Python coverage gate

The `Python suite and packaging` GitHub Actions job runs the complete Python
suite on Python 3.14 with branch coverage enabled. It fails when combined
statement and branch coverage is below 80 percent and uploads `coverage.json`
as the `python-coverage` artifact even when the gate is red.

Run the same gate locally from the repository root:

```bash
python -m pytest tests/ -q --cov=genomes_agentic_os --cov-branch --cov-report=term --cov-report=json:coverage.json --cov-fail-under=80
```

The initial floor comes from the AGE-66 exact-main Python 3.14 baseline:
commit `0a22d46ae34347320892945079a6e2a553d94b0b` passed 1,817 tests with
80.055821646394 percent combined coverage. The floor is monotonic. A later
change may raise it after recording a fresh exact-main baseline, but must not
lower it to make CI pass.

Keep `pytest-cov` identical in both development dependency lists in
`pyproject.toml`; pip reads the `dev` extra while uv reads the `dev` dependency
group.
