# Auto-Dev: review other people's work

Use `/auto-dev-review-others`; it delegates to the canonical `/pr-review`
owner in `review --no-merge` mode. This is an independent assessment of another
author's pull request. It owns neither repairs nor merge execution.

## Inputs

- verified provider, repository, pull request, base branch, author identity,
  and current head revision;
- live diff, changed files, discussion threads, checks, and linked tracker
  scope;
- repository instructions and effective development, QA, review, and GitFlow
  policy;
- relevant sibling pull requests, migrations, generated artifacts, or rollout
  dependencies.

Review the provider's current head, not an old local checkout or pasted diff.
If the head changes during review, invalidate the conclusion and review the new
revision.

## Review method

1. Understand the intended behavior and risk before reading line details.
2. Trace the changed execution and data paths far enough to test the author's
   assumptions.
3. Check correctness, security/privacy, tenancy, data integrity, error paths,
   concurrency, compatibility, migrations, performance, observability,
   maintainability, tests, documentation, and release impact as applicable.
4. Inspect sibling or target-branch interactions when GitFlow creates a pull
   request family. Pay special attention to migration and dependency ordering.
5. Verify existing provider findings and checks instead of restating them.
6. Report only actionable findings. Give each one a severity, tight code
   location, concrete failure mode, and why the current tests do not protect it.
7. Separate blocking correctness findings from optional improvements and
   questions.

Use bounded subagents for distinct risk lenses when the diff is large, but
deduplicate and verify every returned finding against the exact revision before
publishing or recording it.

## Evidence and done criteria

The immutable review receipt names provider, pull request, repository, base,
provider-read author identity, `author_kind: others`, reviewed revision,
review mode, checks considered, findings, and final result.

The stage is complete when all risk areas required by policy were assessed and
the exact reviewed head is either:

- `changes_required`, with actionable findings; or
- `clean`, with `review_mode: review_no_merge` and provider readback.

A clean review hands the hashed receipt to `/auto-dev-merge`. It never repairs
the branch, dismisses findings, approves on behalf of a human, or merges.
