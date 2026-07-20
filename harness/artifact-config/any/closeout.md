---
schema_version: 1
provider: any
artifact_type: closeout
mode: compose
required_sections: [Outcome, Delivered Scope, Validation, External State, Residual Risk, Cleanup, Follow-Up]
format: {renderer: markdown}
approval: {write: explicit}
validation: [completion_is_receipt_backed, remaining_work_is_not_hidden]
---

# Good Closeout

State what is genuinely complete, the evidence, external readback, cleanup, and
what remains. Near-complete, awaiting CI, or awaiting provider apply are not
complete states.
