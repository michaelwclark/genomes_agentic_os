# Review Standard

Review the actual diff, its call sites, tests, configuration, migrations, and
operational effects. Prioritize findings that can cause incorrect behavior,
data loss, security or tenant leakage, compatibility breaks, unrecoverable
operations, misleading observability, or missing test coverage.

For each actionable finding, name the affected path and behavior, explain the
failure mode with concrete evidence, and state the smallest safe correction.
Do not manufacture findings to appear thorough. Distinguish blockers,
follow-ups, questions, and optional polish. Re-read the final head after repairs
before declaring it ready.
