# Team Health Hook

The team-health hook is optional and must be easy for future skills or agents to enable or disable.

Default: off unless the user passes `--team-health on` or repo policy enables it.

The hook must not change review comments. It records structured telemetry only, never personal judgments.

Contract:

```yaml
team_health_hook:
  enabled: false
  author: <github-login>
  repo: <owner/repo>
  pr: <number>
  findings:
    critical: 0
    high: 0
    categories:
      missing-test: 0
      security: 0
      architecture: 0
      missing-docs: 0
  links:
    pr: <url>
    comments:
      - <url>
```

When enabled, report whether telemetry was written. If the sink is unavailable, say so in the final response.
