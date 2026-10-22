# afmux design

Date: 2026-10-22. Status: agreed in brainstorming, awaiting implementation plan.

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
| Concurrency | three parallel `fm respond` all succeed, queued: 4 s, 8 s, 12 s. No lock needed. |
| Speed | ~4.5 s for ~130 words; ~1.3 s for a five-line answer. |
| `fm count-tokens -q` | bare integer on stdout; reads prompt from stdin; `-i` adds instructions to the count. |
| `--schema file` | returns compact valid JSON on stdout. Schema files come from `fm schema`. |
| `--greedy --no-stream` | deterministic, whole answer at once. |
| OpenAI-style `tools` via `fm serve` | not honoured. Not used by afmux. |

## Components

```
afmux/
  SKILL.md                  the only thing loaded into the agent's context
  scripts/afm               Python 3 stdlib, executable, no dependencies
  presets/
    summarise.md
    classify.md
    classify.schema.json
    extract.md
    commit-msg.md
  tests/
    test_afm.py             unittest, runs without the model
    fakefm/fm               PATH shim that imitates fm for the tests
  README.md
  LICENSE
```

### SKILL.md

Under about 80 lines. Contents, in this order:

1. When to delegate: bounded task, no reasoning or code generation, input
   under 7000 tokens, answer is text or flat JSON.
2. When not to: anything needing repo context, multi-step work, or where a
   wrong answer is expensive to detect.
3. The two command shapes (below), with one example each.
4. The exit codes and what to do on each.
5. How to chunk input that is too large: split at paragraph or function
   boundaries, run one call per chunk, merge in the agent.
6. One line: run in the background when the answer is not needed immediately.

### scripts/afm

Single-file Python 3 script using only the standard library. Runs from the
skill checkout with no build or install step. Locates `presets/` relative to
its own path.

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
| `--schema FILE` | JSON schema file passed to `fm respond --schema`; output is validated as JSON | preset's schema if any |
| `--labels a,b,c` | `classify` only: allowed labels, substituted into the preset's `{labels}` placeholder | required for `classify` |
| `--timeout SECONDS` | kill `fm respond` after this long | 120 |
| `--budget TOKENS` | maximum tokens for instructions + input | 7168 (8192 minus 1024 output reserve) |
| `--list` | print preset names and first line of each, then exit 0 | |

#### Behaviour, in order

1. Resolve instructions: preset file contents (with `{labels}` substituted for
   `classify`) or the `ask` argument. Resolve schema: `--schema`, else
   `presets/<name>.schema.json` if it exists, else none.
2. Read all of stdin. Empty input is exit 2.
3. Run `fm count-tokens -q -i <instructions>` with the input on stdin. If the
   count exceeds the budget, exit 2 and print `input is N tokens, budget is M`
   to stderr. Never truncate.
4. Run `fm respond --no-stream --greedy -i <instructions> [--schema FILE]`
   with the input on stdin, under the timeout.
5. If `fm` exits non-zero, pass its stderr through and exit 1.
6. If a schema was used, parse stdout as JSON. On failure print the raw
   output to stderr and exit 3. For `classify`, additionally check that
   `label` is one of `--labels`; otherwise exit 3.
7. Print the answer to stdout: the JSON re-serialised compactly on one line
   when a schema was used, otherwise the model text with trailing whitespace
   stripped. Nothing else goes to stdout.

#### Exit codes

| Code | Meaning | Agent's response |
|---|---|---|
| 0 | success, answer on stdout | use it |
| 1 | `fm` failed (refusal, context overflow, timeout); its message on stderr | do the job yourself |
| 2 | input empty or over budget; count and budget on stderr | chunk and retry |
| 3 | schema requested but output was not valid JSON or label not allowed; raw output on stderr | retry once, then do it yourself |
| 4 | `fm` not found or `fm available` reports the model unavailable | do the job yourself, do not retry |

### Presets

Each preset is a Markdown file whose whole content is the instructions string.
An optional `<name>.schema.json` beside it is passed as the schema.

| Preset | Input | Output | Schema |
|---|---|---|---|
| `summarise` | prose | three to five sentences of prose | none |
| `classify` | text | `{"label": str, "confidence": int 0-100}` | `classify.schema.json` |
| `extract` | text | flat JSON object | caller must pass `--schema` |
| `commit-msg` | a diff | conventional commit subject plus optional body | none |

Everything else uses `ask`. Out of scope for v1: code review, multi-turn
sessions, images, OCR, `fm serve`, tool calling.

## Error handling

- The script never prints partial model output on success paths; the agent
  either gets a whole answer and exit 0, or a non-zero exit and nothing on
  stdout.
- Timeouts kill the `fm` process group so no orphan keeps the model busy.
- `fm available` is checked only when `fm respond` fails, to avoid paying a
  process spawn on every successful call.

## Testing

- `tests/test_afm.py` with `unittest`. It prepends `tests/fakefm` to `PATH`
  so `fm` is the shim; the shim's behaviour is controlled by environment
  variables (token count to report, stdout to emit, exit code, delay) so every
  exit-code path and the timeout are covered without the model.
- One integration test, skipped unless `fm available` succeeds, runs
  `afm classify --labels positive,negative` on a fixed sentence and asserts
  exit 0 and a valid label.
- Run with `python3 -m unittest discover tests`.

## Installation

Symlink the checkout into each agent's skills directory:

- Claude Code: `~/.claude/skills/afmux`
- Codex and OpenCode: their user-level skills directories, to be confirmed
  against current docs when the README is written.

The script is run by path from inside the skill directory, so nothing goes on
`PATH`.

## Non-goals

- No daemon, socket, queue or job files.
- No Swift or FoundationModels framework use in v1. If tool calling or
  sessions become required, `scripts/afm` can be rewritten in Swift behind the
  same SKILL.md contract.
- No prompt caching, retries or backoff inside the script; the agent decides
  whether to retry.
