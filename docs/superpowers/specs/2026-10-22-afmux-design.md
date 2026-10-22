# afmux design

Date: 2026-10-22. Status: revised after review, awaiting implementation plan.

## Purpose

afmux lets a coding agent (Claude Code, Codex, OpenCode) hand small, bounded
jobs to the on-device Apple Foundation Model instead of spending paid tokens on
them. It is a **skill plus one bundled script**. There is no daemon, queue or
server.

"Efficient" here means **agent-token efficient**: the fewest tokens the agent
spends describing a job, dispatching it and reading the answer back. Wall-clock
is secondary and is handled by the agent running the command in the background
when it wants to.

## Why not a broker

- `fm serve` and concurrent `fm respond` processes both serialise on the device.
  A queue adds no throughput.
- A daemon adds lifecycle checks and polling, and every poll costs the agent
  tokens.
- Async is already free: the agent can background a shell command and read the
  output file later.
- The SKILL.md format is shared by all three target agents, so one skill covers
  all of them. A broker would need three client integrations.

## Measured facts about `fm` (macOS 27.0.1, arm64, 2026-10-22)

| Fact | Value |
|---|---|
| Context window | 8192 tokens total (instructions + prompt + output). 8009-token prompt succeeds, 8209 fails. |
| Overflow error | exit 1, stderr `Error: The session's transcript exceeded the model's context size.` |
| Very large input (over ~15k tokens) | misreported as exit 1 `Error: The model's safety guardrails were triggered.` |
| Guardrail refusal | exit 1, empty stdout, stderr `Error: The model's safety guardrails were triggered.` |
| `--guardrails permissive-content-transformations` | a server log with "attack", "injection", "kill switch", "fraud" was refused under default guardrails and summarised correctly under permissive. A diff with "murder", "exploit", "victims" passed under both. |
| Agent sandbox | reported from a sandboxed Claude Code session: `fm available` exits 0 but `fm respond` exits 1 with a ModelManager error 1008, even on a plain prompt. Not reproduced in this (unsandboxed) session. Codex also sandboxes commands by default. |
| Concurrency | three parallel `fm respond` all succeed, queued: 4 s, 8 s, 12 s. No lock needed. |
| Killing the client | SIGTERM or SIGKILL on `fm respond` mid-generation frees the model at once: the next short call ran in 0.5 s, same as idle. |
| Speed | ~4.5 s for ~130 words; 0.5 to 1.3 s for a five-line answer. |
| `fm count-tokens -q` | bare integer on stdout; reads prompt from stdin; `-i` adds instructions to the count. 50 ms warm, 440 ms cold. Does not count a schema. |
| Schema files | must carry `x-order`; a hand-written schema without it is rejected as "data missing". `fm schema object` emits the right shape. |
| `enum` in a schema | honoured by constrained decoding: with `enum: [red, green]` the model answered "green" for the colour of the sky. |
| `--use-case content-tagging` | no measurable gain for closed-label classification: on 8 samples one label improved and one got worse versus `general`. |
| `--greedy --no-stream` | deterministic, whole answer at once. Retrying the same call gives the same output. |
| OpenAI-style `tools` via `fm serve` | not honoured. Not used by afmux. |

## Components

```
afmux/
  SKILL.md                  the only thing loaded into the agent's context
  scripts/afm               Python 3 stdlib, executable, no dependencies
  presets/
    summarise.md
    classify.md             instructions only; schema is generated per call
    extract.md
    commit-msg.md
  tests/
    test_afm.py             unittest, runs without the model
    fakefm/fm               PATH shim that imitates fm for the tests
  README.md
  LICENSE
```

### SKILL.md

Frontmatter:

```yaml
name: afmux
description: Delegate small bounded text jobs (summarise, classify into given labels, extract fields to JSON, draft a commit message, or any short instruction over supplied text) to the free on-device Apple Foundation Model with the `afm` command. Use when the input is under about 7000 tokens, needs no repository context or reasoning, and a wrong answer is cheap to spot. macOS only.
```

The description is what makes an agent reach for the skill, so it is part of
the design, not an implementation detail.

Body under about 80 lines, in this order:

1. When to delegate: bounded task, no reasoning or code generation, input
   under about 7000 tokens, answer is text or flat JSON.
2. When not to: anything needing repo context, multi-step work, or where a
   wrong answer is expensive to detect.
3. The two command shapes (below), with one example each. Input must be
   redirected or piped; `afm` exits at once if stdin is a terminal.
4. The exit codes and what to do on each. Exit 5 means the agent's sandbox
   blocked the model: run `afm` outside the sandbox (Claude Code: add it to
   the sandbox exclusions; Codex: run with sandbox disabled for that command)
   and never retry inside it.
5. How to handle oversized input per preset: `summarise`, `classify` and
   `extract` split at paragraph or function boundaries, one call per chunk,
   merge in the agent. `commit-msg` does not chunk: send `git diff --stat`
   plus the key hunks, or write the message yourself.
6. Background calls queue on the device and the timeout counts queue time, so
   do not fire many at once.

### scripts/afm

Single-file Python 3 script using only the standard library. Runs from the
checkout with no build step. Locates `presets/` relative to its own real path
(after resolving symlinks).

#### Command shapes

```
afm <preset> [options] < input
afm ask "<instructions>" [options] < input
afm --list
```

The payload is always stdin. The agent never quotes large text on a command
line.

#### Options

| Option | Meaning | Default |
|---|---|---|
| `--labels a,b,c` | `classify` only, required: allowed labels. Substituted into the preset's `{labels}` placeholder by plain string replacement and compiled into a schema whose `label` property is an `enum` of exactly these values | |
| `--schema FILE` | JSON schema passed to `fm respond --schema`; output is validated as JSON. Required for `extract`, not allowed with `classify` | none |
| `--guardrails LEVEL` | passed through to `fm respond` | `permissive-content-transformations` |
| `--use-case CASE` | passed through to `fm respond` | `general` |
| `--timeout SECONDS` | kill `fm respond` after this long, measured from process start, so queue time counts | 120 |
| `--budget TOKENS` | maximum tokens for instructions + input + schema | 7168 (8192 minus 1024 output reserve) |
| `--list` | print preset names and the first line of each, then exit 0 | |

Permissive guardrails are the default because every afmux job transforms text
the agent already holds, which is the case that setting exists for, and logs
and diffs trip the default guardrails on ordinary words.

#### Behaviour, in order

1. If stdin is a terminal, exit 2 with `afm reads its input from stdin` on
   stderr. Read all of stdin. Empty input is exit 2.
2. Resolve instructions: preset file contents, with `{labels}` replaced for
   `classify`, or the `ask` argument. Resolve schema: for `classify`,
   generate it in a temporary file from a fixed template (`title`, `type`,
   `properties.label` with the `enum`, `required`, `x-order`,
   `additionalProperties: false`); otherwise `--schema` if given; otherwise
   none.
3. Count tokens: `fm count-tokens -q -i <instructions>` with the input on
   stdin, plus `fm count-tokens -q` of the schema file text when a schema is
   used. The schema count is an approximation of what the model sees, erring
   high. If the sum exceeds the budget, exit 2 with
   `input is N tokens, budget is M` on stderr. Never truncate.
4. Run `fm respond --no-stream --greedy -i <instructions> --guardrails L
   --use-case C [--schema FILE]` with the input on stdin, in its own process
   group, under the timeout. On timeout kill the process group and exit 1
   with `timed out after N s` on stderr.
5. If `fm` cannot be executed at all, exit 4. If `fm respond` exits
   non-zero and its stderr mentions `ModelManager` with error `1008`, exit 5
   with `fm respond is blocked by a sandbox; run afm outside it` on stderr.
   Otherwise run `fm available`; if that fails, exit 4; otherwise pass the
   `fm respond` stderr through and exit 1.
6. If a schema was used, parse stdout as JSON. On failure print the raw
   output to stderr and exit 3. For `classify`, additionally check that
   `label` is one of `--labels` (belt and braces over the enum); otherwise
   exit 3.
7. Print the answer to stdout: the JSON re-serialised compactly on one line
   when a schema was used, otherwise the model text with trailing whitespace
   stripped. Nothing else goes to stdout.

Token counting always spawns `fm count-tokens`. A byte-length shortcut was
considered and rejected: the warm call costs 50 ms against model calls of
seconds, and it is the only check that turns a 15k-token input into a clear
exit 2 instead of a misleading guardrail message.

#### Exit codes

| Code | Meaning | Agent's response |
|---|---|---|
| 0 | success, answer on stdout | use it |
| 1 | `fm` failed (refusal, context overflow, timeout); its message on stderr | do the job yourself |
| 2 | stdin is a terminal, input empty, or over budget; count and budget on stderr | chunk and retry, or do it yourself |
| 3 | schema requested but output was not valid JSON or label not allowed; raw output on stderr | do the job yourself; a retry gives the same output under greedy decoding |
| 4 | `fm` not found or `fm available` reports the model unavailable | do the job yourself, do not retry |
| 5 | `fm respond` blocked by the agent's sandbox (ModelManager error 1008) | run `afm` outside the sandbox; never retry inside it |

### Presets

Each preset is a Markdown file whose whole content is the instructions string.

| Preset | Input | Output | Schema |
|---|---|---|---|
| `summarise` | prose | three to five sentences of prose | none |
| `classify` | text | `{"label": "<one of --labels>"}` | generated per call with `enum` |
| `extract` | text | flat JSON object | caller passes `--schema` |
| `commit-msg` | a diff | conventional commit subject plus optional body | none |

`classify` returns the label only. A self-reported confidence number from a
small model is not calibrated, so it was dropped.

Everything else uses `ask`. Out of scope for v1: code review, multi-turn
sessions, images, OCR, `fm serve`, tool calling.

## Error handling

- The script never prints partial model output on success paths; the agent
  either gets a whole answer and exit 0, or a non-zero exit and nothing on
  stdout.
- Timeouts kill the `fm` process group. Measured: killing the client frees
  the model immediately, so no orphaned generation delays the next call.
- `fm available` is run only after `fm respond` fails, so a successful call
  spawns exactly two processes: `count-tokens` and `respond` (three with a
  schema).
- Detecting the sandbox by matching `1008` in stderr is brittle by nature;
  the string is recorded in the facts table and the test shim reproduces it
  so a change in Apple's wording fails a test rather than silently
  becoming exit 1.

## Testing

- `tests/test_afm.py` with `unittest`. It prepends `tests/fakefm` to `PATH`
  so `fm` is the shim; the shim's behaviour is controlled by environment
  variables (token count to report, stdout to emit, stderr to emit, exit
  code, delay) so every exit-code path including 5 and the timeout are
  covered without the model.
- The generated `classify` schema is asserted field by field, including
  `x-order`, since a schema without it is rejected by `fm`.
- One integration test, skipped unless `fm available` succeeds and
  `fm respond` on a one-word prompt exits 0 (so it also skips in a sandbox),
  runs `afm classify --labels positive,negative` on a fixed sentence and
  asserts exit 0 and a valid label.
- Run with `python3 -m unittest discover tests`.

## Installation

Requirements: macOS 27 or later on Apple silicon with the on-device model
enabled, and the Xcode Command Line Tools (for `/usr/bin/python3` and `git`).

1. Clone the repo.
2. Symlink `scripts/afm` to `~/.local/bin/afm`, and make sure `~/.local/bin`
   is on `PATH`. SKILL.md then invokes plain `afm`, which sidesteps the
   question of how each agent passes the skill's directory to the shell.
3. Symlink the checkout into each agent's skills directory:
   - Claude Code: `~/.claude/skills/afmux`
   - Codex: `~/.codex/skills/afmux`
   - OpenCode: `~/.config/opencode/skills/afmux`
4. Let `afm` run outside the agent's sandbox. The README gives the setting
   for each agent and links its sandbox documentation.

The README links each agent's skills documentation next to its path so a
reader can check the location if an agent moves it.

## Non-goals

- No daemon, socket, queue or job files.
- No Swift or FoundationModels framework use in v1. If tool calling or
  sessions become required, `scripts/afm` can be rewritten in Swift behind the
  same SKILL.md contract.
- No retries or backoff inside the script, and none recommended to the agent
  either: with greedy decoding a retry reproduces the failure.
