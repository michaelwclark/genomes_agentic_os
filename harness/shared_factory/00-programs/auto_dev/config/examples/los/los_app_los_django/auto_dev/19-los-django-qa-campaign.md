# LOS Django QA Campaign

This is the `los_app_los_django` QA-stage policy. It owns the application-ticket
decision; it does not make the QA automation repository guess the product
contract.

For every Jira with an application PR, create or read back one QA Automation
Assessment child issue and keep each root Jira in its own Auto-Dev work item.
Classify it as `playwright_automatable`, `non_browser_automatable`,
`performance_or_observability`, `blocked_by_fixture`,
`blocked_by_product_config_or_rules`, or
`blocked_by_environment_or_provider`.

Create browser automation only for a deterministic browser-visible acceptance
contract. Performance, observability, migration-only, internal-only, and
nondeterministic background-work tickets need an explicit alternative-validation
decision instead.

When browser automation is appropriate, launch the configured
`los_qa_automation` child delivery and bind its QA contract, PR, merged revision,
hosted evidence, fixture/configuration receipt, and disposition back to this
application work item. The root Jira can transition to `Ready for Release` only
after acceptance mapping, semantic prerequisite readback, hosted evidence for
the merged exact revision on the intended tenant/build, and Jira readback.

The child QA-only PR follows the child project's merge policy. Cross-harness
review and application PR-family health are not prerequisites for QA-only test
coverage unless that child policy changes.
