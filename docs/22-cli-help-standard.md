# CLI Help Standard

All `agentic-os` CLI tools and harness/bin scripts follow this standard. New tools must comply before shipping.

## Rules

### 1. Top-level parser always has a two-level description

Every `ArgumentParser` must have a `description=` that answers: *what does this tool do, in one sentence?* A second sentence may add a critical constraint or usage note.

```python
parser = argparse.ArgumentParser(
    description=(
        "One-line imperative: what the tool does. "
        "Optional second sentence for a critical constraint."
    ),
    epilog=env_epilog(...),
    formatter_class=AosHelpFormatter,
)
```

### 2. Every flag gets a `help=` string

No `add_argument` call may omit `help=`. Required flags append `"Required."` to their help string.

```python
parser.add_argument("--jql", required=True, help="JQL query string. Required.")
parser.add_argument("--limit", type=int, default=10, help="Max results to return (default: %(default)s).")
```

Use `%(default)s` whenever the default is non-obvious. Do not use it when the default is already stated in the help text explicitly.

### 3. Dry-run flags describe what 'live' means

```python
parser.add_argument(
    "--dry-run",
    action="store_true",
    help="Preview changes without writing. Live mode calls the Notion API and writes local receipts.",
)
```

### 4. Subcommand parsers inherit description

Each `add_parser(...)` call must also include a `description=` (not just `help=`). The `help=` text appears in the parent's subcommand list; `description=` appears when the user runs `tool <subcommand> --help`.

```python
sub.add_parser(
    "start",
    help="Start a detached quiet run.",
    description=(
        "Launch COMMAND detached from the terminal. "
        "Writes a run directory with stdout/stderr logs and a structured state.json."
    ),
)
```

### 5. Internal-only subcommands are suppressed

Subcommands not intended for direct user invocation use `help=argparse.SUPPRESS` to hide them from the top-level listing.

```python
monitor_parser = subparsers.add_parser("_monitor", help=argparse.SUPPRESS)
```

### 6. Epilog format: ENVIRONMENT, FILES, EXAMPLES

Every tool that reads env vars or config files must include an epilog. Use the `env_epilog()` helper from `src/genomes_agentic_os/cli_help.py` (Python CLI package) or an inline `textwrap.dedent` block (standalone scripts).

```
ENVIRONMENT
  VAR_NAME        What it controls. Default or fallback noted.

CONFIG FILES (read at runtime)
  path/to/file    What this file contains and when it is read.

EXAMPLES
  tool-name --flag value
      One-line description of what this example does.
```

### 7. Use `AosHelpFormatter` for package CLI tools

Import from `src/genomes_agentic_os/cli_help.py`:

```python
from .cli_help import AosHelpFormatter, env_epilog

parser = argparse.ArgumentParser(
    ...,
    epilog=env_epilog(...),
    formatter_class=AosHelpFormatter,
)
```

Standalone bin scripts use `argparse.RawDescriptionHelpFormatter` directly (no package dependency).

### 8. Hardcoded defaults are named constants

Any hardcoded path or default that affects behavior must be a named constant near the top of the file, with a comment explaining it.

```python
# Default manifest path; override with --manifest.
DEFAULT_MANIFEST = ROOT / "harness/shared_factory/00-control-plane/automation-run-tracking.yml"
```

## Template snippet

Minimum viable help for a standalone bin script:

```python
import argparse
import textwrap

_EPILOG = textwrap.dedent("""\
    ENVIRONMENT
      MY_ENV_VAR    What it does (default: ~/agentic_os).

    EXAMPLES
      my-tool --flag value
          One-line description.
""")

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="One-line imperative description.",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--flag", help="What this flag does (default: %(default)s).", default="value")
    return parser
```

## Checklist before shipping a new CLI tool

- [ ] `description=` present on the top-level parser
- [ ] `description=` present on every public subcommand parser
- [ ] `help=` present on every `add_argument` call (required flags include `"Required."`)
- [ ] `--dry-run` help text states what the live path does
- [ ] Epilog has ENVIRONMENT section listing all env vars the tool reads
- [ ] Epilog has FILES section listing all config files the tool reads at runtime
- [ ] Epilog has EXAMPLES section with at least two concrete invocations
- [ ] `formatter_class=AosHelpFormatter` (package CLI) or `RawDescriptionHelpFormatter` (bin scripts)
- [ ] Internal/private subcommands suppressed with `help=argparse.SUPPRESS`
- [ ] `%(default)s` used in help strings for flags with non-obvious defaults
