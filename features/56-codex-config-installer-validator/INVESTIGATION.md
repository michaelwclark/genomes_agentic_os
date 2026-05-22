# Investigation

The requested `install.py` and `docs/03-installation/index.md` paths were not present in this branch. The live package exposes the installer surface through the `agentic-os` CLI in `src/genomes_agentic_os/cli.py`, validation logic in `src/genomes_agentic_os/validate.py`, and installation docs under `docs/10-cli-and-install/README.md`.

Existing validation only checked generated OS roots. There was no separate preflight for source-package files such as `templates/agent-config/codex-config-layer-map.yml`.

Implementation therefore adds the preflight to the existing validation module and creates the requested `docs/03-installation/` docs as a focused install-validation entrypoint.
