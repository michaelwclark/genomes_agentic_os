# Harness Bin

Reserved for executable wrappers owned by the installed Agentic OS harness.

Current required executables live outside this folder:

- `agentic-os` is the Python package console entrypoint.
- `context-mode` is expected at `/Users/genome/.local/bin/context-mode`.
- `agentic-os-context-mode` is the local context-mode status and kill-switch wrapper.

Add scripts here only when the OS package owns the wrapper and the script is safe
to mirror into installed roots.
