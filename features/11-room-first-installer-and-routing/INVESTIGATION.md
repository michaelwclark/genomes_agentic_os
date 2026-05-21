# Investigation

- Default `init` must stay backward compatible.
- Customer/profile installs cannot use the default-domain initializer directly because it creates Genome-specific rooms.
- Room files need a generated marker so reruns preserve hand-authored edits.
