---
name: afmux
description: Use the free on-device Apple Foundation Model for two jobs. `afm read FILE --ask "question"` answers a question about a long file from verified quotes so you never read the file into context. `afm run steps/` implements modules from your tests and short specs, tests them, and reports once; steps it cannot get right, you write yourself. macOS only.
---

# afmux

You design, the on-device model implements, tests judge. Keep your own tokens low: short specs, one attempt, then take over. Don't read code that passed; grepping it for a constraint is fine.

### Steps, in one tool call

Write the test files, any scaffolding (`__init__.py`), and the step files with one script, then run `afm`. Paths are relative to the directory you run `afm` in; `test:` runs there too, and a dotted test path needs `tests/__init__.py`.

**One step per module.** A step is one file:

```
# steps/01-util.md
file: src/util.py                          # the file this step writes; if it exists, the model sees it and rewrites it whole
test: python3 -m unittest tests.test_util  # exit 0 = pass
context: src/types.py                      # optional, comma-separated: only the modules this file imports
---
Module util.py.

parse_date(s): "YYYY-MM-DD" -> (year, month, day) as ints. Parts must be exactly 4, 2 and 2 digits; month 1-12, day 1-31; anything else raises ValueError. No datetime.
Examples: parse_date("2026-01-07") == (2026, 1, 7); parse_date("2026-1-7") raises ValueError.

slugify(s): lowercase, each run of characters other than a-z and 0-9 becomes one hyphen, strip hyphens from both ends.
Examples: slugify("Hello, World!") == "hello-world"; slugify("!!!") == "".
```

A spec is plain English: one or two sentences per function with the signature, the rule, the edge cases, and one or two examples. No numbered steps, no pseudocode, no algorithm. Say exactly what is ambiguous (character classes, padding, tie-breaks, the empty case) and nothing else. Library calls you care about go in as literal lines (`parser.add_argument("file")`): the model invents API names otherwise.

Measured on five small modules from prose specs: the model got 3 of 8 right, all of them trivial (a CSV loader, a filter, a summary). It failed parsing with positional fields, calendar arithmetic, argparse wiring and anything with an off-by-one trap, and a retry almost never changes its output. Expect to write those yourself.

### Run

```
afm run steps/              # every step in filename order, stop at the first failure
afm step steps/01-util.md   # one step
afm run steps/ --json       # machine-readable report
afm run steps/ --retries 0  # default 1; also --timeout S (120), --budget T (7168)
```

After a step passes, `afm` reruns every earlier step's tests, so a rewrite that breaks earlier code fails here. A step whose test already passes is reported `pass 0 (already passing)` and not regenerated, so a rerun after you implement a step by hand is safe. The report ends with `N/M steps passed, T tests, R retries, W warnings`; a step whose test command ran 0 tests gets a warning.

### Read a long file without reading it

```
afm read docs/guide.md --ask "Which setting turns the sandbox off?"   # one question per call
afm read docs/guide.md --ask "..." --chunk-tokens 1500                 # default 600; bigger chunks are faster but miss more
```

`afm` splits the file into chunks, asks the model per chunk whether it contains a passage that answers the question, and prints only verified quotes with line ranges (a quote that is not in the file is dropped). You never see the file; logs without blank lines are split at lines, and a chunk the model refuses is counted and skipped. Answer from the quotes and cite the lines they give; expect some irrelevant matches, and read the file only if nothing useful comes back. Borrowed from the MinionS protocol (HazyResearch), where the cloud model never reads the document.

### Exit codes

| Exit | Meaning | Do |
| :--- | :--- | :--- |
| 0 | every step passed | done; check the summary line's warnings |
| 1 | a step failed after its retry, or the model errored | do not rewrite the spec; implement that one file yourself from your tests (`<file>.afm-failed` may have usable parts), make sure your file passes its test, and rerun `afm run` so the remaining steps continue; a hand-written file that fails its test is regenerated over |
| 2 | bad step file or arguments | fix it |
| 4 | `fm` missing or model unavailable | implement the steps yourself |
| 5 | blocked by the sandbox | rerun outside it (Claude Code: `dangerouslyDisableSandbox: true`, or `afm *` in `excludedCommands`) |
| 6 | a step's prompt is over budget | split that step or trim its context |
