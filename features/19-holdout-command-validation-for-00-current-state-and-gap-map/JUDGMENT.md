# Judgment

## Command Applicability

Feature 00 is a backlog and runtime mirror feature, so holdout validation should
exercise docs install/update and validation instead of inventing a nonexistent
feature-specific command.

## Output Capture

The raw docs install output is intentionally summarized because it lists many
created runtime files. The important evidence is that the expected plan files
exist, `docs update` is idempotent, and validation passes before and after the
update.

