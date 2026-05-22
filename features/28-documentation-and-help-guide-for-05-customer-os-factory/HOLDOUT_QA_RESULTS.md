# Holdout QA Results

## Guide Reference Check

```text
$ rg "customer init|customer update|customer validate|core_errors|profile_warnings|private source" docs/13-feature-guides/05-customer-os-factory.md
present, it must match the slug passed to `customer init`.
agentic-os customer init acme_ops \
agentic-os customer update acme_ops --root /tmp/acme_os
agentic-os customer validate --root /tmp/acme_os
`core_errors: []`, and any non-blocking profile issues under
`profile_warnings`.
`customer init` creates root-level routing files, `customer.yml`, a customer
`customer update` is additive. It uses the same write-once behavior as the
`customer validate` separates hard runtime failures from customer profile
- `core_errors` covers missing required customer root files and domain
- `profile_warnings` covers missing optional customer profile fields, domain
  warnings, and private source-owner terms found in generated markdown or YAML.
The private-term scan is a guardrail. If `profile_warnings` mentions a private
If `customer init` rejects the profile, check that the command slug matches
If validation reports missing root files, rerun `customer update` and review
If validation reports private source terms, remove or replace that content in
```

## Full Suite

```text
$ uv run --extra dev pytest -q
.......................................                                  [100%]
39 passed in 3.39s
```
