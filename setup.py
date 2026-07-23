"""Build hook that bundles the Agentic OS scaffold assets into wheels.

The CLI needs more than Python modules: a fresh install must carry the harness,
templates, operating manual, and JSON schemas it installs. Editable source
checkouts continue to use the repository copies; built distributions receive a
private package resource copy.
"""

from __future__ import annotations

from pathlib import Path
import shutil

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py


RESOURCE_DIRECTORIES = ("harness", "templates", "operating-manual", "schemas")


class build_py(_build_py):
    """Copy source-owned non-Python resources into the wheel build tree."""

    def run(self) -> None:
        super().run()
        repository = Path(__file__).resolve().parent
        destination = Path(self.build_lib) / "genomes_agentic_os" / "_resources"
        for name in RESOURCE_DIRECTORIES:
            source = repository / name
            if source.is_dir():
                shutil.copytree(source, destination / name, dirs_exist_ok=True)


setup(cmdclass={"build_py": build_py})
