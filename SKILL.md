---
name: afmux
description: Implement well-specified modules on the free on-device Apple Foundation Model. You write the tests and a spec per module; `afm run` implements each on the local model, tests it, checks it didn't break earlier steps, retries once, and reports once. Use for boilerplate-heavy code where the spec is much shorter than the code; for small functions it costs more tokens than writing them. macOS only.
---

# afmux

You design, the on-device model implements, tests judge. Don't read code that passed; grepping it for a constraint is fine. If the spec would be as long as the code, write the code.

### Steps, in one tool call

Write the test files and the step files together with one script (a heredoc per file), then run `afm`. That is three tool calls for the whole task: write, run, done. All paths are relative to the directory you run `afm` in; `test:` runs there too, and a dotted test path needs `tests/__init__.py`.

**One step per module** unless its prompt would pass about 4k tokens (spec + current file + context). A step is one file:

```
# steps/01-util.md
file: src/util.py                          # the one file this step writes; if it exists, the model sees it and rewrites it whole
test: python3 -m unittest tests.test_util  # exit 0 = pass
context: src/types.py                      # optional, comma-separated, read-only; may be a file an earlier step writes
---
Module `util.py` with two functions. Keep every existing function unchanged.

def parse_date(s):
1. Split s on "-". If not exactly 3 parts: raise ValueError.
2. If len(parts[0]) != 4 or len(parts[1]) != 2 or len(parts[2]) != 2, or any part is not str.isdigit(): raise ValueError.
3. month outside 1..12 or day outside 1..31: raise ValueError.
4. return (int(parts[0]), int(parts[1]), int(parts[2]))
Examples: parse_date("2026-01-07") == (2026, 1, 7); parse_date("2026-1-7") raises ValueError.

def slugify(s):
1. s = s.lower()
2. s = re.sub(r"[^a-z0-9]+", "-", s)   # the exact class; not \w
3. return s.strip("-")
```

What passes: numbered lines of near-code with exact indices, character classes, variable types, padding, ordering, tie-breaks, the empty case, and two or three examples. Library calls as literal lines (`parser.add_argument("file")`), never described. Nested control flow as indented lines, never `a.`/`b.` labels or `; then` prose: the model turns labels into variables and flattens prose.

### Run

```
afm run steps/              # every step in filename order, stop at the first failure
afm step steps/01-util.md   # one step
afm run steps/ --json       # machine-readable report
afm run steps/ --retries 0  # default 1; also --timeout S (120), --budget T (7168)
```

After a step passes its test, `afm` reruns the tests of every earlier step, so a rewrite that breaks earlier code fails here, not later. A step whose test already passes is reported `pass 0 (already passing)` and not regenerated: rerun after fixing a spec, or implement a step by hand and rerun; both are safe. Steps take a few seconds each on an idle machine and queue behind other `afm` runs.

### Exit codes

| Exit | Meaning | Do |
| :--- | :--- | :--- |
| 0 | every step passed | done; the report lists any retry reasons and duplicate-definition warnings |
| 1 | a step failed after retries, or the model errored | the report shows each attempt's failing test and exception, head and tail of the output, `<file>.afm-failed` (the attempt; read it to see what the model did) and `<file>.afm-failed.log`; the original is restored or the new file removed, and both files are deleted when the step later passes. Fix the spec once; if it fails again, implement that step yourself and rerun |
| 2 | bad step file or arguments | fix it |
| 4 | `fm` missing or model unavailable | implement the steps yourself |
| 5 | blocked by the sandbox | rerun outside it (Claude Code: `dangerouslyDisableSandbox: true`, or `afm *` in `excludedCommands`) |
| 6 | a step's prompt is over budget | split that step or trim its context |
