#!/bin/bash
# afmux installer. One line:
#   curl -fsSL https://raw.githubusercontent.com/antvinni/afmux/main/install.sh | bash
# or from a checkout: ./install.sh
#
# Idempotent. Environment overrides: AFMUX_DIR (checkout location, default
# ~/.afmux), AFMUX_REPO (git URL or local path to clone from).
set -euo pipefail

repo="${AFMUX_REPO:-https://github.com/antvinni/afmux}"
dir="${AFMUX_DIR:-$HOME/.afmux}"
rule='For mechanical implementation work that tests can judge, break it into small steps with a spec and a test each and run them with `afm run` (see the afmux skill) instead of writing the code yourself.'
marker='<!-- afmux standing rule -->'

say()  { printf '%s\n' "$*"; }
fail() { printf 'afmux install: %s\n' "$*" >&2; exit 1; }

# 1. Requirements
[ "$(uname -s)" = "Darwin" ] || fail "afmux needs macOS (Apple Foundation Models are macOS only)"
[ "$(uname -m)" = "arm64" ]  || fail "afmux needs Apple silicon"
command -v git >/dev/null     || fail "git not found; install the Xcode Command Line Tools: xcode-select --install"
command -v python3 >/dev/null || fail "python3 not found; install the Xcode Command Line Tools: xcode-select --install"
command -v fm >/dev/null      || fail "fm not found; afmux needs macOS 27 or later with the on-device model"
if ! fm available >/dev/null 2>&1 </dev/null; then
  fail "the on-device model is not available (fm available failed); enable Apple Intelligence in System Settings"
fi

# 2. Checkout: use the directory this script lives in if it is a checkout, else clone or update
here=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then   # run from a file, not piped via stdin
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi
if [ -n "$here" ] && [ -x "$here/scripts/afm" ] && [ -z "${AFMUX_DIR:-}" ]; then
  dir="$here"
  say "using checkout at $dir"
elif [ -d "$dir/.git" ]; then
  git -C "$dir" pull -q --ff-only </dev/null && say "updated $dir"
else
  git clone -q "$repo" "$dir" </dev/null && say "cloned afmux into $dir"
fi
[ -x "$dir/scripts/afm" ] || fail "$dir does not contain scripts/afm"

# Which agents are present, decided before any directory is created below
have_claude=0;   [ -d "$HOME/.claude" ] && have_claude=1
have_codex=0;    [ -d "$HOME/.codex" ] && have_codex=1
have_opencode=0; [ -d "$HOME/.config/opencode" ] && have_opencode=1

# 3. afm on PATH
mkdir -p "$HOME/.local/bin"
ln -sfn "$dir/scripts/afm" "$HOME/.local/bin/afm"
say "linked ~/.local/bin/afm"
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *)
    profile="$HOME/.zprofile"
    if ! grep -qs 'afmux' "$profile"; then
      printf '\n# afmux\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$profile"
      say "added ~/.local/bin to PATH in $profile (open a new terminal, or: source $profile)"
    fi
    ;;
esac

# 4. Skill directories: Claude Code reads ~/.claude/skills, Codex reads ~/.agents/skills, OpenCode reads both
for skills in "$HOME/.claude/skills" "$HOME/.agents/skills"; do
  mkdir -p "$skills"
  ln -sfn "$dir" "$skills/afmux"
  say "linked $skills/afmux"
done

# 5. Per-agent configuration, only for agents that are present
add_rule() {  # add_rule FILE
  mkdir -p "$(dirname "$1")"
  if ! grep -qsF "$marker" "$1"; then
    printf '\n%s\n%s\n' "$marker" "$rule" >> "$1"
    say "added the standing rule to $1"
  fi
}

if [ "$have_claude" = 1 ]; then
  python3 - "$HOME/.claude/settings.json" <<'PY'
import json, os, shutil, sys
path = sys.argv[1]
cfg = {}
if os.path.exists(path):
    try:
        with open(path) as f:
            cfg = json.load(f)
    except ValueError as e:
        sys.exit("afmux install: %s is not valid JSON (%s); fix it or add \"afm *\" to sandbox.excludedCommands yourself" % (path, e))
if not isinstance(cfg, dict):
    sys.exit("afmux install: %s is not a JSON object; add \"afm *\" to sandbox.excludedCommands yourself" % path)
sb = cfg.setdefault("sandbox", {})
ex = sb.setdefault("excludedCommands", [])
if "afm *" not in ex:
    ex.append("afm *")
    if os.path.exists(path):
        shutil.copy2(path, path + ".afmux-backup")
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    print("added 'afm *' to sandbox.excludedCommands in " + path + (" (backup: " + path + ".afmux-backup)" if os.path.exists(path + ".afmux-backup") else ""))
PY
  add_rule "$HOME/.claude/CLAUDE.md"
fi

if [ "$have_codex" = 1 ]; then
  add_rule "$HOME/.codex/AGENTS.md"
fi

if [ "$have_opencode" = 1 ]; then
  python3 - "$HOME/.config/opencode/opencode.json" <<'PY'
import json, os, shutil, sys
path = sys.argv[1]
cfg = {"$schema": "https://opencode.ai/config.json"}
if os.path.exists(path):
    try:
        with open(path) as f:
            cfg = json.load(f)
    except ValueError as e:
        sys.exit("afmux install: %s is not valid JSON (%s); fix it or allow \"afm *\" under permission.shell yourself" % (path, e))
if not isinstance(cfg, dict):
    sys.exit("afmux install: %s is not a JSON object; allow \"afm *\" under permission.shell yourself" % path)
shell = cfg.setdefault("permission", {}).setdefault("shell", {})
if shell.get("afm *") != "allow":
    shell["afm *"] = "allow"
    if os.path.exists(path):
        shutil.copy2(path, path + ".afmux-backup")
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    print("allowed 'afm *' in " + path)
PY
  add_rule "$HOME/.config/opencode/AGENTS.md"
fi

# 6. Done
say ""
say "afmux is installed: afm run <steps-dir> implements test-gated steps on the on-device model."
say "See SKILL.md for how an agent writes steps."
