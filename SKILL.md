---
name: afmux
description: Implement small, well-specified steps on the free on-device Apple Foundation Model so the code is written locally and never leaves the machine. You break the task into one-function or one-edit steps, each with a tight spec and a test command; `afm run` executes them, tests each, and reports once. Use for mechanical implementation work where tests can judge the result; expect about half the steps to come back to you. macOS only.
---

# afmux

You design, the on-device model implements, tests judge. Never read code that passed.

### Steps

One step = one function, class or edit to one file. Write the test file first; the model never sees it. Then the step file:

```
# steps/01-parse-date.md
file: src/util.py                          # the one file this step writes
test: python3 -m unittest tests.test_util  # exit 0 = pass
context: src/types.py                      # optional, read-only reference files
---
Write a Python function `parse_date(s)`.
Input "YYYY-MM-DD". Output a tuple of three ints (year, month, day).
Raise ValueError for: wrong part count, non-digits, parts not 4-2-2 wide, month outside 1-12, day outside 1-31. No datetime.
Examples: parse_date("2026-01-07") == (2026, 1, 7); parse_date("2026-1-7") raises ValueError.
```

A spec the model gets right: signature, behaviour in plain sentences, two or three examples, every edge case with its expected result, interfaces it depends on under `context:`. Spell out padding, ordering, tie-breaks, widths and the empty case; the model fails on anything it has to infer. Keep each prompt (spec + current file + context) under about 4k tokens.

### Run

```
afm run steps/              # every step in filename order, stop at the first failure
afm step steps/03-x.md      # one step
afm run steps/ --json       # machine-readable report
afm run steps/ --retries 0  # also --timeout S (120), --budget T (7168)
```

### Exit codes

| Exit | Meaning | Do |
| :--- | :--- | :--- |
| 0 | every step passed | done; do not open the files |
| 1 | a step failed after retries, or the model errored | read the test output and `<file>.afm-failed` in the report (original restored, new file removed); fix the spec or implement that one step yourself; rerun |
| 2 | bad step file or arguments | fix it |
| 4 | `fm` missing or model unavailable | implement the steps yourself |
| 5 | blocked by the sandbox | rerun outside it (Claude Code: `dangerouslyDisableSandbox: true`, or `afm *` in `excludedCommands`) |
| 6 | a step's prompt is over budget | split that step or trim its context |

Steps after a failure are reported `skipped`; rerun after fixing. Expect 3 to 4 of 7 steps to pass first time, in 3 to 5 seconds each.
