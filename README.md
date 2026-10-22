# afmux

afmux turns Apple's free on-device Foundation Model into an implementer for coding agents (Claude Code, Codex, OpenCode). The agent breaks a task into small test-gated steps and writes each step's spec and tests; `afm run` implements each step locally, runs its tests, retries once, and reports back once. The agent reads test results, never passing code, and the code never leaves the machine.

### Features

| Feature | Description |
| :--- | :--- |
| **Test-gated steps** | One file, one test command, one spec per step. Exit 0 from the test command is the only judge. |
| **One report** | A table of steps, then the test output and saved attempt for the first failure. Nothing else on stdout. |
| **Safe failure** | On a final failure the original file is restored (or a new one removed) and the attempt is kept at `<file>.afm-failed`. |
| **Local only** | Runs on the macOS 27 `fm` CLI. No network, no API key, no cost. |
| **Sandbox aware** | Detects the sandbox block (`ModelManagerError 1008`) and exits 5 instead of failing silently. `afm run` takes arguments only, so one `excludedCommands` entry covers it. |
| **No dependencies** | One Python 3 stdlib script; macOS 27 on Apple silicon with the Command Line Tools. |

### Accuracy

Seven single-function specs, hidden tests, one retry, measured 2026-10-22:

| Implementer | Tasks passed | Tests passed | Cost |
| :--- | :--- | :--- | :--- |
| on-device model via `afm` | 3 to 4 of 7 | 37 of 48 | $0 |
| Claude Haiku 5.5 | 7 of 7 | 48 of 48 | $0.01 |
| Claude Sonnet 5.5 | 7 of 7 | 48 of 48 | $0.04 |

It passes steps that transcribe the spec and fails on rules it has to infer (padding, widths, off-by-ones), without repairing them from test output. Plan for about half the steps coming back. This is a privacy tool, not a cost tool.

### Installation

```
# One line (checks requirements, clones to ~/.afmux, links afm and the skill, configures installed agents)
curl -fsSL https://raw.githubusercontent.com/antvinni/afmux/main/install.sh | bash

# From a clone, in place
./install.sh

# By hand
git clone https://github.com/antvinni/afmux ~/.afmux
ln -sf ~/.afmux/scripts/afm ~/.local/bin/afm
ln -sfn ~/.afmux ~/.claude/skills/afmux    # Claude Code and OpenCode
ln -sfn ~/.afmux ~/.agents/skills/afmux    # Codex and OpenCode
```

The installer also adds `afm *` to Claude Code's `sandbox.excludedCommands`, allows `afm *` in OpenCode's `permission.shell`, and appends a standing rule to `~/.claude/CLAUDE.md` and the agents' `AGENTS.md`. It is idempotent and backs up any JSON it rewrites.

### Usage

```
# A step: header, ---, spec. Tests live in your repo and are never shown to the model.
cat steps/01-parse-date.md
file: src/util.py
test: python3 -m unittest tests.test_util
context: src/types.py
---
Write a Python function `parse_date(s)`. Input "YYYY-MM-DD", output (year, month, day) as ints.
Raise ValueError for anything else: wrong part count, non-digits, parts not 4-2-2 wide,
month outside 1-12, day outside 1-31. No datetime.
Examples: parse_date("2026-01-07") == (2026, 1, 7); parse_date("2026-1-7") raises ValueError.

# Run every step in filename order, stop at the first failure
afm run steps/

# Run one step
afm step steps/03-log-line.md

# Machine-readable report
afm run steps/ --json

# Options
afm run steps/ --retries 0 --timeout 60 --budget 6000
```

```
step            file          result  attempts
01-parse-date   src/util.py   pass    1
02-slugify      src/util.py   pass    2
03-log-line     src/log.py    FAIL    2
04-report       src/report.py skipped -

step 03-log-line failed after 2 attempts
test: python3 -m unittest tests.test_log
...
attempt saved at src/log.py.afm-failed; src/log.py restored
```

| Exit | Meaning |
| :--- | :--- |
| 0 | every step passed |
| 1 | a step failed after its retries, or the model errored on it |
| 2 | bad step file or arguments |
| 4 | `fm` missing or model unavailable |
| 5 | blocked by the agent's sandbox |
| 6 | a step's prompt is over the token budget; split it |

[`SKILL.md`](SKILL.md) tells the agent how to write steps the model gets right: signature, behaviour, examples, every edge case, nothing left to infer.

### Tests

```
python3 -m unittest discover tests
```

Runs against a fake `fm`; one integration step runs on the real model when available. The installer is tested against a throwaway `HOME`.

### Licence

MIT.
