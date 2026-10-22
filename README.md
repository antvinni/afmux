# afmux

Pipe command output or a file into `afm` and get back a short answer from the
free on-device Apple Foundation Model, without the text ever entering your
coding agent's context or leaving the machine.

    pytest 2>&1 | afm ask "list each failing test and its error, one per line"
    git diff --cached | afm commit-msg
    afm extract --schema s.json < build.log

afmux is a skill for Claude Code, Codex and OpenCode plus one Python script.
There is no daemon, server or queue. The design and its measurements are in
[`docs/superpowers/specs/2026-10-22-afmux-design.md`](docs/superpowers/specs/2026-10-22-afmux-design.md).

## Requirements

- macOS 27 or later on Apple silicon, with the on-device model enabled
  (`fm available` prints `System model available`).
- Xcode Command Line Tools, for `/usr/bin/python3` and `git`.
- One of Claude Code, Codex CLI or OpenCode.

## Install

```bash
git clone https://github.com/antvinni/afmux ~/src/afmux
mkdir -p ~/.local/bin && ln -sf ~/src/afmux/scripts/afm ~/.local/bin/afm   # ~/.local/bin must be on PATH
mkdir -p ~/.claude/skills ~/.agents/skills
ln -sfn ~/src/afmux ~/.claude/skills/afmux    # Claude Code (OpenCode reads this too)
ln -sfn ~/src/afmux ~/.agents/skills/afmux    # Codex (OpenCode reads this too)
afm --list
```

Skill locations, as documented by each agent:

| agent | user-level skills directory | docs |
|---|---|---|
| Claude Code | `~/.claude/skills/` | [Skills](https://code.claude.com/docs/en/skills) |
| Codex | `~/.agents/skills/` | [Build skills](https://learn.chatgpt.com/docs/build-skills) |
| OpenCode | `~/.config/opencode/skills/`, and it also reads `~/.claude/skills/` and `~/.agents/skills/` | [Skills](https://opencode.ai/docs/skills/) |

The script is invoked as plain `afm`, so the agent never has to know where
the skill directory is.

## Tell the agent when to use it

Skill descriptions alone trigger weakly for a tool whose point is saving
tokens. Add this standing rule to your `CLAUDE.md` (Claude Code) or
`AGENTS.md` (Codex, OpenCode):

```
When you need only a summary, a label, some fields or a commit message from command output or a file, pipe it into `afm` (see the afmux skill) instead of reading it yourself.
```

You can also invoke it by name: `/afmux` in Claude Code, `$afmux` in Codex,
or "use afm for this" anywhere.

## Let `afm` reach the model from inside the agent's sandbox

Inside a sandboxed shell, `fm available` succeeds but `fm respond` and
`fm count-tokens` fail with `ModelManagerServices.ModelManagerError error
1008`. `afm` reports that as exit 5 and tells the agent to run it outside the
sandbox.

**Claude Code.** Add `afm` to the sandbox exclusions in `~/.claude/settings.json`:

```json
{
  "sandbox": {
    "excludedCommands": ["afm *"]
  }
}
```

Two documented limits of `excludedCommands` matter here: every command in
the call must match, and a redirect or command substitution keeps the whole
call sandboxed. So `pytest 2>&1 | afm ask "..."` and `afm summarise <
build.log` still run sandboxed even with the entry above, which only helps
calls like `afm --list`. When a call is sandboxed, `afm` exits 5 and the
skill tells Claude to rerun the same command with `dangerouslyDisableSandbox:
true`; the prompt is titled "Bash command (unsandboxed)", and in auto and
bypass modes it runs without a prompt. See
[Sandboxing](https://code.claude.com/docs/en/sandboxing).

**Codex.** Codex has no per-command exclusion. Either approve the sandbox
escalation when Codex asks, or run with `--sandbox danger-full-access` for
sessions that use `afm`. See [Agent approvals and
security](https://learn.chatgpt.com/docs/agent-approvals-security).

**OpenCode.** OpenCode gates commands with permission rules rather than an
OS sandbox. To skip the prompt, allow the pattern in `opencode.json`:

```json
{
  "permission": {
    "shell": {
      "afm *": "allow"
    }
  }
}
```

See [Permissions](https://opencode.ai/docs/permissions/).

## Optional: nudge hook for Claude Code

`hooks/nudge-large-output` is a PostToolUse hook. When a Bash result is over
a threshold (default 3000 tokens, set `AFMUX_NUDGE_TOKENS` to change it), it
tells Claude that piping into `afm` would have been cheaper. It fires at the
moment of waste, which no other trigger does. Add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Bash",
        "hooks": [{"type": "command", "command": "~/.claude/skills/afmux/hooks/nudge-large-output"}]
      }
    ]
  }
}
```

## Commands and exit codes

See [`SKILL.md`](SKILL.md): presets, options, the exit-code table and what
the agent should do on each code. In short: 0 answer, 1 model failed, 2 usage,
3 bad JSON, 4 model unavailable, 5 sandbox, 6 input over budget (rerun with
`--chunk`).

## Tests

```bash
python3 -m unittest discover tests
```

The suite runs against a fake `fm` on `PATH` and needs no model. One
integration test runs only when the real model answers, and skips otherwise.

Whether agents actually reach for the skill is measured separately; see
[`tests/trigger-eval/README.md`](tests/trigger-eval/README.md).

## Licence

MIT, see [`LICENSE`](LICENSE).
