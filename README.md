# afmux

An implementer for coding agents that runs on the free on-device Apple
Foundation Model. The agent (Claude Code, Codex, OpenCode) breaks a task into
small test-gated steps and writes each step's spec and tests; `afm run`
implements each step on the local model, runs its tests, retries once, and
reports back once. The agent reads test results, never passing code, and the
code is written on the machine.

```
afm run steps/
```

```
step            file          result  attempts
01-parse-date   src/util.py   pass    1
02-slugify      src/util.py   pass    1
03-log-line     src/log.py    FAIL    2

step 03-log-line failed after 2 attempts
test: python3 -m unittest tests.test_log
...
attempt saved at src/log.py.afm-failed; src/log.py restored
```

## What to expect

Measured on 2026-10-22 with seven single-function specs, hidden tests and one
retry, the same specs given to two cloud models for comparison:

| implementer | tasks fully passed | tests passed | time | cost |
|---|---|---|---|---|
| on-device model via `afm` | 4 of 7 | 37 of 48 | 30 s | $0 |
| Claude Haiku 5.5 | 7 of 7 | 48 of 48 | 30 s | $0.010 |
| Claude Sonnet 5.5 | 7 of 7 | 48 of 48 | 28 s | $0.037 |

The on-device model passed every step whose logic was a direct transcription
of the spec, including an edit to an existing module. It failed on padding
rules, an off-by-one field count and digit-width validation, and did not
repair them from the failing tests. Rerunning the same seven specs through
`afm run` gave 3 of 7: with greedy decoding, small wording differences in the
prompt flip individual steps. So afmux is not a cost tool: a Haiku subagent
did the same work for a cent. It is for code that must stay on the machine,
and for the spec-plus-tests handoff discipline, with the agent expecting
about half the steps to come back to it.

## Requirements

- macOS 27 or later on Apple silicon, with the on-device model enabled
  (`fm available` prints `System model available`).
- Xcode Command Line Tools, for `/usr/bin/python3` and `git`.
- One of Claude Code, Codex CLI or OpenCode.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/antvinni/afmux/main/install.sh | bash
```

It checks the requirements, clones afmux into `~/.afmux` (or updates it),
puts `afm` on your `PATH` via `~/.local/bin`, links the skill into
`~/.claude/skills` and `~/.agents/skills`, and for each agent it finds adds
the standing rule and the sandbox or permission setting below. Safe to run
again. Set `AFMUX_DIR` to choose the checkout location, or run `./install.sh`
from a clone to use that clone in place.

By hand:

```bash
git clone https://github.com/antvinni/afmux ~/.afmux
mkdir -p ~/.local/bin && ln -sf ~/.afmux/scripts/afm ~/.local/bin/afm   # ~/.local/bin must be on PATH
mkdir -p ~/.claude/skills ~/.agents/skills
ln -sfn ~/.afmux ~/.claude/skills/afmux    # Claude Code (OpenCode reads this too)
ln -sfn ~/.afmux ~/.agents/skills/afmux    # Codex (OpenCode reads this too)
```

Skill locations: Claude Code reads `~/.claude/skills/`
([docs](https://code.claude.com/docs/en/skills)); Codex reads
`~/.agents/skills/` ([docs](https://learn.chatgpt.com/docs/build-skills));
OpenCode reads `~/.config/opencode/skills/` and both of the others
([docs](https://opencode.ai/docs/skills/)).

## Step files

A step is one markdown file; a run is a directory of them, executed in
filename order.

```
file: src/util.py
test: python3 -m unittest tests.test_util
context: src/types.py, src/errors.py
---
Write a Python function `parse_date(s)` ...
```

| key | required | meaning |
|---|---|---|
| `file` | yes | the one file the step creates or rewrites, relative to where `afm` runs |
| `test` | yes | shell command run from the same directory; exit 0 means the step passed |
| `context` | no | files shown to the model as read-only reference, such as interfaces from earlier steps |

The body is the spec. [`SKILL.md`](SKILL.md) says what a good one contains:
signature, behaviour, examples, every edge case, and nothing the model has to
infer. Tests are never shown to the model.

## Commands and exit codes

```
afm run <steps-dir> [--retries N] [--timeout S] [--budget T] [--json]
afm step <step-file> [same options]
```

| exit | meaning |
|---|---|
| 0 | every step passed |
| 1 | a step failed after its retries, or the model errored on it; the report has the test output and the saved attempt |
| 2 | bad step file or arguments |
| 4 | `fm` missing or model unavailable |
| 5 | blocked by the agent's sandbox |
| 6 | a step's prompt is over the token budget; split it |

On a final failure the original file is restored (or a newly created one
removed) and the last attempt is kept at `<file>.afm-failed`.

## Tell the agent when to use it

The installer adds this to `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md` and
`~/.config/opencode/AGENTS.md` for the agents it finds; per project, put it
in `CLAUDE.md` or `AGENTS.md`:

```
For mechanical implementation work that tests can judge, break it into small steps with a spec and a test each and run them with `afm run` (see the afmux skill) instead of writing the code yourself.
```

Or invoke it by name: `/afmux` in Claude Code, `$afmux` in Codex.

## Sandboxes

Inside a sandboxed shell, `fm` fails with `ModelManagerServices.ModelManagerError
error 1008` and `afm` exits 5. Because `afm run` takes arguments and never a
pipe or redirect, one exclusion entry is enough in Claude Code
(`~/.claude/settings.json`, added by the installer):

```json
{"sandbox": {"excludedCommands": ["afm *"]}}
```

Codex has no per-command exclusion: approve the escalation or run with
`--sandbox danger-full-access`. OpenCode gates commands with permission rules,
not an OS sandbox; the installer allows `afm *` under `permission.shell`.

## Tests

```bash
python3 -m unittest discover tests
```

Runs against a fake `fm` on `PATH` and needs no model. One integration test
runs a real step when the model answers and skips otherwise. The installer
is tested against a throwaway `HOME`.

## Licence

MIT, see [`LICENSE`](LICENSE).
