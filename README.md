# afmux

afmux puts Apple's free on-device Foundation Model to work for coding agents (Claude Code, Codex, OpenCode) in two ways. `afm read` answers a question about a long file from verified quotes, so the agent never reads the file into its context. `afm run` implements test-gated steps from the agent's specs and tests, and reports back once.

The agent breaks a task into small test-gated steps and writes each step's spec and tests; `afm run` implements each step locally, runs its tests, retries once, and reports back once.

### Installation

```
curl -fsSL https://raw.githubusercontent.com/antvinni/afmux/main/install.sh | bash
```


### Features

| Feature | Description |
| :--- | :--- |
| **Test-gated steps** | One file, one test command, one spec per step. Exit 0 from the test command is the only judge. |
| **One report** | A table of steps, then the test output and saved attempt for the first failure. Nothing else on stdout. |
| **Safe failure** | On a final failure the original file is restored (or a new one removed) and the attempt is kept at `<file>.afm-failed`. |
| **Read mode** | `afm read FILE --ask "..."` chunks a long file, asks the model per chunk, and returns only quotes verified to be in the file, with line ranges. The MinionS idea: the main model never reads the document. |
| **Local only** | Runs on the macOS 27 `fm` CLI. No network, no API key, no cost. |
| **Sandbox aware** | Detects the sandbox block (`ModelManagerError 1008`) and exits 5 instead of failing silently. `afm run` takes arguments only, so one `excludedCommands` entry covers it. |
| **No dependencies** | One Python 3 stdlib script; macOS 27 on Apple silicon with the Command Line Tools. |

### Usage

```
# Claude Code: hand the skill a task
/afmux implement parse_date, slugify and parse_log_line in src/util.py, with tests

# Codex
$afmux implement parse_date, slugify and parse_log_line in src/util.py, with tests

# Any agent: just ask; the installer's standing rule points mechanical, test-gated work at afmux
> add a --json flag to cli.py that prints the counts as a JSON object

# Answer a question about a long file without reading it (one question per call)
afm read docs/guide.md --ask "Which setting turns the sandbox off?"

# What the agent runs to implement steps
afm run steps/              # every step in filename order, stop at the first failure
afm step steps/03-x.md      # one step
afm run steps/ --json       # machine-readable report
afm run steps/ --retries 0  # no retry; also --timeout S, --budget T
```

[`SKILL.md`](SKILL.md) has the step-file format, the exit codes, and what a spec the model gets right looks like.

### Tests

```
python3 -m unittest discover tests
```

### Licence

MIT.
