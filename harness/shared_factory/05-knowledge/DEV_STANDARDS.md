# DEV_STANDARDS

The canonical composable development-standards plane is `dev_standards/`.
Load every `*.md` file except `README.md` from the ordered root, domain, and
project folders declared by `project.yml dev_factory.dev_standards.paths`.

`quality-gates/` remains a compatibility alias during migration. New rules
and configuration must use `DEV_STANDARDS` and `dev_standards` naming.
