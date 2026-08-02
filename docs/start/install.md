---
title: Install it
sidebar_label: Install it
slug: /start/install
description: Install the agentic-os command-line tool, create your first OS folder, and confirm it worked.
---

# Install it

**What this is for:** getting the `agentic-os` command onto your machine and
creating your first OS folder.

**Where it applies:** macOS and Linux. You need Python 3 and a terminal. Fifteen
minutes.

If you want more detail than this page gives — every flag, every failure mode —
read [Install and quickstart](/docs/01-install-and-quickstart) instead. This
page is the short version.

## 1. Get the tool

Clone the repository and install it into a virtual environment:

```bash
git clone https://github.com/michaelwclark/genomes_agentic_os.git
cd genomes_agentic_os
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

`-e` means "editable" — the installed command points back at this folder, so
pulling updates updates the tool. `'.[dev]'` also installs the test framework;
drop the `[dev]` part if you only want to run it, not develop it.

You now have two commands, `agentic-os` and its short alias `aos`. They are the
same thing.

```bash
agentic-os --help
```

## 2. Try it somewhere disposable first

Before you point it at a folder you care about, run it against a temporary
directory. This sequence is verified end to end:

```bash
tmpdir=$(mktemp -d)
agentic-os init --target "$tmpdir/os"
agentic-os validate --root "$tmpdir/os"
agentic-os config install --root "$tmpdir/os" --layer agentic_os_root --apply
agentic-os config doctor --root "$tmpdir/os" --layer agentic_os_root
find "$tmpdir/os" -maxdepth 2 | sort
```

Read the `find` output. That is the shape of an OS folder, and it is worth two
minutes of looking at before you go further.

:::note The order matters

`config doctor` looks for a settings file that only `config install` creates. If
you run `config doctor` straight after `init`, it exits with an error saying the
file is missing. That is not a bug — it is telling you which step you skipped.

:::

## 3. Create your real one

```bash
agentic-os init --target ~/agentic_os
```

This creates `~/agentic_os` with two areas of work already in it: `personal` and
`work`. You can add more later, or pass `--domains` to choose your own at
creation time.

:::caution Documentation drift

Some handbook pages say `init` creates three default areas — `personal`, `work`
and `archive`. The current code creates two, `personal` and `work`. Trust the
`find` output from your own install over any page that disagrees with it.

:::

## 4. Check it is healthy

Two commands you will use often:

```bash
agentic-os validate --root ~/agentic_os   # is the folder structure intact?
agentic-os doctor --fix-missing           # deeper check, repairs what it safely can
```

Run `validate` whenever something feels wrong. Run `doctor` when `validate`
passes but the system still is not behaving.

## 5. Point your agent at it

Start a Claude Code or Codex session with `~/agentic_os` as the working
directory. The `AGENTS.md` file at the root tells the agent what to read and in
what order, so it will orient itself.

That file is the entry point for everything else. If you ever wonder "how does
the agent know about any of this," the answer is: it reads `AGENTS.md`, and
`AGENTS.md` tells it where to go next.

## What to do next

- Look around the folder you just made. Open a few files.
- Read [Domains and projects](./domains-and-projects.md) to understand what the
  top-level folders are.
- If something failed, [Troubleshooting and FAQ](/docs/18-troubleshooting-and-faq)
  lists the common causes by exit code.
