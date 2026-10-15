# Shared SSH and sudo access

Agentic OS workflows, Claude, Codex, and Atlas executions with a local host
executor use `harness/bin/agentic-os-host`. It is a portable Python 3 executable
and does not require the package, a login shell, an SSH agent, or a terminal.

```sh
~/agentic_os/harness/bin/agentic-os-host check --sudo
~/agentic_os/harness/bin/agentic-os-host run genomesbox -- /usr/bin/id -un
~/agentic_os/harness/bin/agentic-os-host sudo workmac -- /usr/bin/id -u
~/agentic_os/harness/bin/agentic-os-host sudo bigmac -- /bin/sh -c 'command1 && command2'
```

The root defaults to `$AGENTIC_OS_ROOT` or `~/agentic_os`; `--root PATH` overrides
it. The private `hosts.env` must be owned by the executing user, have mode 0600
or 0400, and contain `GENOMESBOX`, `BIGMAC`, and `WORKMAC` variables with suffixes
`_HOST_NAME`, `_USER`, and `_PASS`. Values are literal dotenv assignments,
optionally quoted or prefixed by `export`. Shell substitutions are never run.
Keep this file outside version control, prompts, task definitions, and evidence.

SSH uses public keys with password fallback and agent authentication disabled.
Host keys must already be trusted. Fleet provisioning should generate a
dedicated key on each host, exchange only public keys, preserve existing SSH
configuration, and pin host keys obtained over an authenticated connection.
Route unreachable pairs through an authorized jump host in SSH configuration.
Private keys remain on the host that generated them. Protect the SSH directory
and private keys with modes 0700 and 0600 respectively.

Sudo reads the stored password through a private pipe and invalidates its cache
for every invocation. The elevated command receives `/dev/null` as stdin so an
unused password cannot become command input, including under NOPASSWD rules.
Pass a shell script as an argument or execute an authorized remote file when
needed. Command arguments are shell-quoted; use an explicit shell for pipelines.
Output is buffered and known passwords are redacted. Avoid commands that dump
credential files or other secrets; redaction is a final precaution, not a
general secret classifier. Exit codes propagate; deadline expiry returns 124.

The default deadline is 60 seconds, with a maximum of 120 seconds per command.
Use the managed long-running execution route for longer work. A terminated SSH
client does not establish that remote descendants stopped; inspect remote state
before replaying a timed-out mutation.

The file supplies authentication, not authorization for arbitrary actions.
Ordinary task scope and production, destructive, deployment, provider, and
customer-facing approval rules still apply. Do not ask the operator to paste
passwords or manually repeat a sudo command when the configured helper works.
On failure, report the host label, phase, exit status, and recovery prerequisite
without credential values. Never disable host-key verification to recover.

Atlas cloud-only tasks cannot read files on a private host. They must invoke an
authorized local host executor that loads this shared contract. A local mirror
of a cloud task definition does not change its provider prompt or execution
capabilities; record that distinction when reporting integration coverage.
