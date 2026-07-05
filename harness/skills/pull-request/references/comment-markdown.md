# GitHub Comment Markdown

The final `Copy/Paste comment for GH` is what the user may paste directly into a PR review. It must be readable GitHub-flavored markdown.

## Quick

Use for small, obvious fixes.

```markdown
Is there a regression test covering this branch? I could not find one that covers the empty `counter_offer_details` case, and this is the path that would prevent the original bug from coming back.

Suggested code:
```python
def test_empty_counter_offer_details_uses_default_recipient(...):
    ...
```
```

## Standard

Use for most HIGH findings.

```markdown
### Can this lookup return an object outside the current tenant?

I think this can return an object outside the current tenant because the new query uses `Application.objects.get(id=...)` directly. The nearby flow in `los/applications/services/example.py` scopes through the tenant-aware manager first.

Could this use the same pattern?

```python
application = Application.objects.for_tenant(request.tenant).get(id=application_id)
```
```

## Deep

Use for complex security, architecture, data, migration, or acceptance risks.

```markdown
### How does this migration behave during a rolling deploy?

I think this can fail while old web containers are still running because the migration makes `foo_id` non-null before the old code writes it.

Risk path:

- Old code writes `LoanEvent` without `foo_id`.
- New migration rejects the insert.
- Any request still routed to an old container can 500 until the rollout finishes.

Would a two-step migration be safer here?

1. Add nullable column.
2. Backfill existing rows.
3. Deploy code that writes the column.
4. Make it non-null in a follow-up deploy.
```

Rules:

- Do not over-format quick fixes.
- Do not use tables unless comparing multiple cases.
- Do not use Mermaid unless a flowchart makes the issue easier to act on.
- Always include a code suggestion when the fix is clear.
- Lead with a question, but vary the phrasing from comment to comment. The three examples above deliberately use three different openers; a review where every comment starts with the same stock phrase ("Have you considered…") reads as a template, not a reviewer.

