---
name: afmux
description: Implement small, well-specified steps on the free on-device Apple Foundation Model so the code is written locally and never leaves the machine. You break the task into one-function or one-edit steps, each with a tight spec and a test command; `afm run` executes them, tests each, and reports once. Use for mechanical implementation work where tests can judge the result; expect about half the steps to come back to you. macOS only.
---

# afmux: the on-device implementer

You design, the on-device model implements, tests judge. You never read code
that passed its tests.

## Break the work into steps

One step is one function, one class, or one edit to one file. For each step
write two things before running anything:

1. **The test file.** Hidden from the model. It is the only judge.
2. **The step file**, `steps/NN-name.md`: three header lines, a `---` line,
   then the spec.

```
file: src/util.py
test: python3 -m unittest tests.test_util
context: src/types.py
---
Write a Python function `parse_date(s)`.
Input: "YYYY-MM-DD". Output: a tuple of three ints (year, month, day).
Raise ValueError for anything else: wrong number of parts, non-digit parts,
parts not 4-2-2 digits wide, month outside 1-12, day outside 1-31. No datetime.
Examples: parse_date("2026-01-07") == (2026, 1, 7); parse_date("2026-1-7")
raises ValueError; parse_date("2026-13-01") raises ValueError.
```

A spec the model gets right states the signature, the behaviour in plain
sentences, two or three examples, every edge case with its expected result,
and the interfaces it depends on (list those files under `context:`). Say
what to do, not how. Keep each prompt under about 4k tokens: the spec, the
current file for an edit, and the context files all count.

The model fails on rules it has to infer. Spell out padding, ordering,
tie-breaks, validation widths and "what happens on empty". If a rule is
subtle, give it its own example.

## Run

```
afm run steps/          # every step in filename order, stop at the first failure
afm step steps/03-x.md  # one step
afm run steps/ --json   # machine-readable report
```

Options: `--retries N` (default 1; each retry shows the model the failing
test output), `--timeout S` per model call (120), `--budget T` prompt tokens
(7168).

## Read the report, not the code

| exit | meaning | what to do |
|---|---|---|
| 0 | every step passed | done; do not open the files |
| 1 | a step failed after its retries, or the model errored on it | the report shows the test command, the test output, and where the attempt was saved (`<file>.afm-failed`; the original was restored or the new file removed). Fix the spec if the model misread it, or implement that one step yourself. Then rerun from that step |
| 2 | a bad step file or bad arguments; reason on stderr | fix the step file |
| 4 | `fm` missing or the model unavailable | implement the steps yourself |
| 5 | blocked by your sandbox | rerun the same command outside the sandbox (Claude Code: `dangerouslyDisableSandbox: true`; `afm run` takes arguments only, so an `excludedCommands` entry for `afm *` also works) |
| 6 | a step's prompt is over budget; the step is named | split that step or trim its context |

Later steps are reported as `skipped` after a failure; rerun after fixing
and the passed steps simply pass again.

## Expectations

Measured on seven single-function specs: the model passed 3 to 4 of 7
depending on prompt wording, and did not repair the rest from test output.
Plan for that: tight specs, a test file per step, and about half the steps
coming back to you. It is as fast as a cloud call, about 3 to 5 seconds per
step.
