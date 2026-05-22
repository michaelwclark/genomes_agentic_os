# Investigation

Feature 00 acceptance depends on source artifacts, Build Runner state, and installed-runtime plan copies. Existing tests cover runtime plan installation, but a holdout operator needs a focused command that checks the feature 00 contract directly and explains failures in one place.

The holdout command should create a temporary Agentic OS root, run the package CLI against it, and inspect local files only. That keeps it deterministic and avoids accidental board writes.
