# /pr-review

Invoke the canonical M2 PR review workflow.

## Usage

```text
/pr-review <PR-number-or-URL> [--mode review|report|review+merge]
  [--post|--no-post] [--quick]
```

Load `harness/skills/pr-review/SKILL.md` after routing. Every run creates or
reuses a canonical work-item packet and writes its receipts there. A chat run
defaults to display-only review; posting, approval, and merge require the mode
and authority described by the skill and routed project profile.
