---
name: afmux
description: Implement small, well-specified steps on the free on-device Apple Foundation Model. You break the task into one-function or one-edit steps, each with a tight spec and a test command; `afm run` executes them, tests each, retries once, and reports once. Use for mechanical implementation work where tests can judge the result; expect about half the steps to need a spec fix or your own code, and more tokens than writing it yourself. macOS only.
---

# afmux

You design, the on-device model implements, tests judge. Don't read code that passed; grepping it for a constraint (no `datetime`, no imports) is fine.

### Steps

One step = one function, class or edit to one file. Write the step's tests first; the model never sees them. All paths are relative to the directory you run `afm` in, and `test:` runs there too.

```
# steps/01-parse-date.md
file: src/util.py                          # the one file this step writes; if it exists, the model sees it and rewrites it whole
test: python3 -m unittest tests.test_util  # exit 0 = pass
context: src/types.py, src/errors.py       # optional, comma-separated, read-only; may be a file an earlier step writes
---
Write a Python function `parse_date(s)`.
1. Split s on "-". Anything but exactly 3 parts: raise ValueError.
2. Parts must be 4, 2 and 2 ASCII digits wide (check each with str.isdigit and len); otherwise ValueError.
3. month outside 1..12 or day outside 1..31: ValueError.
4. Return (int(year), int(month), int(day)).
Examples: parse_date("2026-01-07") == (2026, 1, 7); parse_date("2026-1-7") raises ValueError.
```

What passes: a numbered algorithm with exact indices, character classes (`[a-z0-9]`, not `\w`), variable types ("current line is a str"), padding, ordering, tie-breaks and the empty case, plus two or three examples. Prose that leaves anything to infer fails. Keep spec + current file + context under about 4k tokens.

Several steps building one file: each step's `test:` must pass with only the functions written so far, so use one test module or class per step (`python3 -m unittest tests.test_util.ParseDateTests`). The model rewrites the whole file each step, so tell it to keep existing functions unchanged.

### Run

```
afm run steps/              # every step in filename order, stop at the first failure
afm step steps/03-x.md      # one step
afm run steps/ --json       # machine-readable report
afm run steps/ --retries 0  # default 1; also --timeout S (120), --budget T (7168)
```

A step whose test already passes against the current file is reported `pass 0 (already passing)` and not regenerated. So rerun the same command after fixing a spec, and implement a step by hand when you take it over: the next run leaves it alone. Steps take a few seconds each on an idle machine; concurrent `afm` runs queue on the one device.

### Exit codes

| Exit | Meaning | Do |
| :--- | :--- | :--- |
| 0 | every step passed | done |
| 1 | a step failed after retries, or the model errored | the report shows the first failing test, head and tail of the output, `<file>.afm-failed` (the attempt) and `<file>.afm-failed.log` (full output); the original is restored or the new file removed. Fix the spec once; if it fails again, implement that step yourself and rerun |
| 2 | bad step file or arguments | fix it |
| 4 | `fm` missing or model unavailable | implement the steps yourself |
| 5 | blocked by the sandbox | rerun outside it (Claude Code: `dangerouslyDisableSandbox: true`, or `afm *` in `excludedCommands`) |
| 6 | a step's prompt is over budget | split that step or trim its context |

Steps after a failure are reported `skipped`. A step that passed on a retry lists why its first attempt failed, so you can tighten the next spec.
