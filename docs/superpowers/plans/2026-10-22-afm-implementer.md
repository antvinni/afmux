# afm implementer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace pipe-mode afmux with `afm run` / `afm step`: execute agent-written, test-gated steps on the on-device model and report once.

**Architecture:** One stdlib Python script. Step files parsed into (file, test, context, spec); a prompt builder; the existing `run_fm` policy; a step runner that writes, tests, retries and restores; a text or JSON reporter. Tests drive a fake `fm` whose N-th reply comes from a sequence directory.

**Tech Stack:** Python 3 stdlib, macOS 27 `fm`.

**Spec:** `docs/superpowers/specs/2026-10-22-afm-implementer-design.md`

## Global Constraints

- Keep `run_fm`, `count_tokens`, signal handling and exit codes 4/5 from the current `scripts/afm`.
- Exit codes: 0 pass, 1 step failed or fm failed on it, 2 usage, 4 unavailable, 5 sandbox, 6 over budget.
- Only the report goes to stdout.
- `python3 -m unittest discover tests` must pass without the model.
- Commits end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

---

### Task 1: Fake fm sequence mode, step parsing, usage errors
- [ ] Add `FAKEFM_RESPOND_SEQ` to `tests/fakefm/fm`: N-th respond call prints `<dir>/N`.
- [ ] Tests: `parse_step` on a good file; missing `file` → exit 2; missing `test` → exit 2; no `---` → exit 2; empty body → exit 2; `afm run` on a missing dir or a dir with no `.md` files → exit 2; steps ordered by filename.
- [ ] Implement `parse_step(path) -> Step(id, file, test, context, spec)`, `load_steps(dir)`, argparse for `run`/`step`, `main` skeleton that lists steps as "pass 0" placeholders? No: implement through Task 2 before asserting results; this task's tests only cover usage errors and ordering (via `--json` with a fake that returns trivial code).
- [ ] Commit.

### Task 2: One step end to end: prompt, write, test, report
- [ ] Tests: pass first try writes the file and reports `pass 1`, exit 0; respond stdin contains the spec and, for an existing file, "Current contents of"; context file content appears under "Reference only"; fences stripped; tests are not in the prompt; `--json` shape; `afm step FILE`.
- [ ] Implement `build_prompt`, `run_step`, `report_text`, `report_json`.
- [ ] Commit.

### Task 3: Retry, final failure, restore and stop
- [ ] Tests: fail then pass → `pass 2`, retry prompt contains previous code and the failing output; fail twice → exit 1, original restored, `.afm-failed` written, report names test command and shows output; created file deleted on final failure; later steps not run; fm failure on a step → exit 1 naming the step; sandbox → 5; over budget → 6 naming the step and advice.
- [ ] Implement.
- [ ] Commit.

### Task 4: Integration test, SKILL.md, README, installer, spec cross-check
- [ ] Integration test: real model, a slugify step with tests, skipped if unavailable.
- [ ] SKILL.md per the spec; README rewritten (what it is, the evidence table, install one-liner, step format, commands, exit codes, standing rule, sandbox note); installer: drop the hook step and `--list`, keep everything else; update `tests/test_install.py` expectations.
- [ ] Run the seven benchmark specs through `afm run` on the real model as the smoke test.
- [ ] Commit, PR, merge.
