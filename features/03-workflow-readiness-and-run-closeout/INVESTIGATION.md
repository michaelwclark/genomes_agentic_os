# Investigation

- Existing workflow scaffolds already create the required runtime files from `WORKFLOW_FILES`.
- The generated context template uses `Source Links` and `Operating Constraints`, so readiness checks align to those headings.
- Run logs store the workflow or automation name in the metadata table, which can be used to update workflow progress on closeout.
- Project status updates need an explicit `--project` argument because current run logs do not yet carry project identity.
