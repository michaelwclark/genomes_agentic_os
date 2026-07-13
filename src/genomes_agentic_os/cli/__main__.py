"""Preserve ``python -m genomes_agentic_os.cli`` from the pre-split module form."""

from . import main

if __name__ == "__main__":
    raise SystemExit(main())
