# Python Source

This repository uses the standard Python `src` layout:

```text
repository root/
  pyproject.toml
  src/                    import isolation root; not a Python package
    genomes_agentic_os/   the importable `genomes_agentic_os` package
```

The repeated name is intentional. `src/` prevents tests and local commands from
accidentally importing files directly from the checkout; the package must be
installed exactly as users receive it. `genomes_agentic_os/` is the real Python
namespace used by `import genomes_agentic_os` and the `agentic-os` console entry.

See [`genomes_agentic_os/README.md`](genomes_agentic_os/README.md) for the module
map and [`../docs/architecture/system-architecture.md`](../docs/architecture/system-architecture.md)
for the full dependency rules.
