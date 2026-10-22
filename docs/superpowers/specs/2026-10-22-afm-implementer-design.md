# afm implementer design

Date: 2026-10-22. Status: agreed.

## Purpose

afmux lets a coding agent hand the *implementation* of small, test-gated steps
to the free on-device Apple Foundation Model. The agent does the design work:
it breaks a task into steps, writes each step's spec and tests, and reads only
test results. `afm` does the execution: it runs each step on the model, runs
the tests, retries once, and reports back once, on completion or at the
first failure.

Nothing else. An earlier pipe-mode design (summarise, classify, extract,
commit messages on piped text) was built and benchmarked first; three rounds
showed it never beat the agent's own shell tools on cost, latency or
accuracy, so it was removed.

## Evidence this shape can work

Measured 2026-10-22 on the on-device model with seven single-function specs,
hidden tests and one retry (same specs given to Haiku and Sonnet):

| implementer | tasks fully passed | tests passed | total time | cost |
|---|---|---|---|---|
| on-device `fm` | 4 of 7 | 37 of 48 | 30 s | $0 |
| Haiku 5.5 | 7 of 7 | 48 of 48 | 30 s | $0.010 |
| Sonnet 5.5 | 7 of 7 | 48 of 48 | 28 s | $0.037 |

The model passed every step whose logic was a direct transcription of the
spec, including a modify-an-existing-module step. It failed on padding and
format rules, an off-by-one field count and digit-width validation, and did
not repair those from the failing test output. So: specs must be tight,
tests are the gate, and the agent should expect to take over roughly one step
in three.

This is not a cost tool against Haiku, which did the same work for a cent.
It is for work that must stay on the machine, and for the discipline of
spec-plus-tests handoff, which the agent benefits from with any implementer.

## Measured facts about `fm` (macOS 27.0.1, arm64, 2026-10-22)

| Fact | Value |
|---|---|
| Context window | 8192 tokens total (instructions + prompt + output). 8009-token prompt succeeds, 8209 fails with `transcript exceeded the model's context size`. |
| Very large input (over ~15k tokens) | misreported as `The model's safety guardrails were triggered`. |
| `fm count-tokens -q` | bare integer; reads the prompt from stdin; `--instructions=` adds the instructions to the count. ~50 ms warm. |
| Instructions | passed as `--instructions=<text>` so text starting with `-` works. |
| `--greedy --no-stream` | deterministic; a retry of the same prompt gives the same output. |
| Agent sandbox | `fm available` passes but `fm respond` and `fm count-tokens` fail with `ModelManagerServices.ModelManagerError error 1008`. Claude Code's `excludedCommands` covers `afm run DIR` (arguments only, no pipe or redirect). |
| Concurrency | concurrent calls queue on the device without failing. |
| Killing the client | SIGTERM or SIGKILL mid-generation frees the model at once. |
| Speed | 3 to 5 s for a one-function implementation; ~4.5 s per 130 words of prose. |
| Usage errors | stderr carries ANSI colour codes; refusals do not. |

## Components

```
afmux/
  SKILL.md              how the agent breaks work into steps and calls afm
  scripts/afm           Python 3 stdlib: run steps on fm, test, retry, report
  tests/test_afm.py     unittest against the fake fm
  tests/fakefm/fm       the shim
  tests/test_install.py
  install.sh
  README.md, LICENSE
```

## Step files

A step is one markdown file. A run is a directory of step files, executed in
filename order (so `01-`, `02-` prefixes order them). Header lines, then a
line `---`, then the spec body:

```
file: src/util.py
test: python3 -m unittest tests.test_util
context: src/types.py, src/errors.py
---
Write a Python function `parse_date(s)` ...
```

| key | required | meaning |
|---|---|---|
| `file` | yes | the one file this step creates or rewrites, relative to the directory `afm` runs in |
| `test` | yes | shell command run from the same directory; exit 0 means the step passed |
| `context` | no | comma-separated files shown to the model as read-only reference (interfaces from earlier steps) |

The body is the spec. SKILL.md says what a good one contains. A step with
no `file` or no `test` is a usage error: an untested step cannot be reported
as done.

## Commands

```
afm run <steps-dir> [options]     run every step in order, stop at the first failure
afm step <step-file> [options]    run one step
```

| option | meaning | default |
|---|---|---|
| `--retries N` | retries per step, each with the failing test output | 1 |
| `--timeout S` | per `fm` call | 120 |
| `--budget T` | maximum prompt tokens per call | 7168 |
| `--json` | machine-readable report on stdout | off |

## Behaviour of one step

1. Parse the step file (usage error on a bad header). Read the current
   content of `file` if it exists, and each `context` file.
2. Build the prompt: fixed instructions ("you are implementing one step;
   output only the complete contents of `<file>`, no fences, no explanation,
   standard library only unless the spec says otherwise"), then the spec,
   then for an existing file "Current contents of `<file>`, output the
   complete modified file:" with the content, then each context file under
   "Reference only, do not modify: `<path>`".
3. Count tokens. Over budget is exit 6 naming the step: `step 03-report:
   prompt is 9120 tokens, budget is 7168; split the step or trim its
   context`.
4. Run `fm respond --no-stream --greedy --instructions=<fixed>` with the
   prompt on stdin, through the single `run_fm` policy (cannot run → 4,
   sandbox 1008 → 5, timeout → step failure). Strip a markdown fence if the
   model added one anyway. Empty output is a step failure.
5. Write `file` (creating directories as needed) and run `test` with
   `shell=True` from the run directory, 120 s timeout. Exit 0 passes.
6. On failure with retries left: new prompt = spec + "Your previous
   implementation:" + code + "It failed these tests; output the complete
   corrected file:" + last 1800 characters of test output. Go to 3.
7. On final failure: restore the file's original content (or delete it if
   the step created it), save the last attempt beside it as
   `<file>.afm-failed`, and stop the run.

Tests are never shown to the model unless the agent puts them in the spec.

## Report

Text (default): one line per step, then details for the failing step.

```
step            file          result  attempts
01-parse-date   src/util.py   pass    1
02-slugify      src/util.py   pass    2
03-log-line     src/log.py    FAIL    2

step 03-log-line failed after 2 attempts
test: python3 -m unittest tests.test_log
<last 60 lines of test output>
attempt saved at src/log.py.afm-failed; src/log.py restored
```

`--json`: `{"steps": [{"id", "file", "result", "attempts", "seconds"}],
"failed": {"id", "test", "output", "saved"} | null}`.

Exit codes: 0 all steps passed; 1 a step failed its tests after retries, or
`fm` failed on it; 2 usage (bad step file, missing directory, no steps);
4 `fm` missing or model unavailable; 5 sandbox; 6 a step over budget.
Nothing but the report goes to stdout.

## SKILL.md

Under about 80 lines. Frontmatter description written for the moment an
agent has a task it could hand off:

> Implement small, well-specified steps on the free on-device Apple
> Foundation Model so the code is written locally and never leaves the
> machine. You break the task into one-function or one-edit steps, each with
> a tight spec and a test command; `afm run` executes them, tests each, and
> reports once. Use for mechanical implementation work where tests can judge
> the result; expect to take over about one step in three. macOS only.

Body: how to break work down (one function or one edit per step; spec =
signature, behaviour, examples, edge cases, interfaces it depends on; tests
written before the step, hidden from the model; context files for interfaces
from earlier steps; keep each prompt under about 4k tokens); the two
commands; the exit codes and what to do (6: split the step; 1: read the
saved attempt and the test output, fix the spec or take over that step only;
5: rerun outside the sandbox); the rule to never read passing code; the
standing rule for CLAUDE.md.

## Testing

`tests/test_afm.py` against the fake `fm`, which gains
`FAKEFM_RESPOND_SEQ=<dir>`: the N-th `respond` call returns the contents of
`<dir>/N`. Covered: step parsing and usage errors; ordering; prompt assembly
(spec, current content for existing files, context files, retry prompt with
failing output); pass first try; fail then pass on retry; fail after retries
with restore, delete-if-created and `.afm-failed`; stop at first failure;
`fm` failure, sandbox and budget exits naming the step; `--json`; `afm step`;
signals; one integration test on the real model, skipped when unavailable.

`tests/test_install.py` unchanged except the installer no longer mentions the
hook.

## Non-goals

No pipe mode, presets, chunking, schemas, hooks or trigger evaluation. No
multi-file steps. No parallel steps: the device serialises anyway. No
self-planning: breaking work into steps is the agent's job.
