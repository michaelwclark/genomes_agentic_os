# Memory

The customer OS factory holdout can be run without modifying source files:

1. `uv run --extra dev pytest -q`
2. `uv run agentic-os customer init acme_ops --profile customer_profiles/example-customer.yml --target <tmp>/acme_os`
3. `uv run agentic-os customer update acme_ops --root <tmp>/acme_os`
4. `uv run agentic-os customer validate --root <tmp>/acme_os`
5. `grep -RInE 'Michael Clark|Genome'\''s Agentic OS|Flywheel|source-owner|source owner' <tmp>/acme_os --include='*.md' --include='*.yml' --include='*.yaml'`

The negative private-name scan should return no matches for the generated
customer root.
