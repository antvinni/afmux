#!/bin/bash
# usage: run.sh [claude|codex|opencode ...]   (default: all three that are installed)
# Runs each task headless in a fresh fixture, in two settings, and saves transcripts.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
date="$(date +%F)"
out="$here/out/$date"; mkdir -p "$out"
rule='When you need only a summary, a label, some fields or a commit message from command output or a file, pipe it into `afm` (see the afmux skill) instead of reading it yourself.'
harnesses=("$@"); [ ${#harnesses[@]} -eq 0 ] && harnesses=(claude codex opencode)
command -v timeout >/dev/null || { echo "run.sh needs GNU timeout (brew install coreutils)" >&2; exit 1; }
python3 -c "import json;[print(t['id'], t['should_trigger'], json.dumps(t['prompt'])) for t in json.load(open('$here/tasks.json'))]" |
while read -r id should prompt_json; do
  prompt="$(python3 -c "import sys,json;print(json.loads(sys.argv[1]))" "$prompt_json")"
  for h in "${harnesses[@]}"; do
    command -v "$h" >/dev/null || continue
    for setting in skill skill+rule; do
      fx="$(mktemp -d)"; "$here/fixture/make-fixture.sh" "$fx" >/dev/null
      if [ "$setting" = "skill+rule" ]; then printf '%s\n' "$rule" > "$fx/CLAUDE.md"; cp "$fx/CLAUDE.md" "$fx/AGENTS.md"; fi
      log="$out/$h-$setting-$id.txt"
      case "$h" in
        claude)   (cd "$fx" && timeout 300 claude -p "$prompt" --output-format stream-json --verbose) > "$log" 2>&1 </dev/null ;;
        codex)    (cd "$fx" && timeout 300 codex exec "$prompt") > "$log" 2>&1 </dev/null ;;
        opencode) (cd "$fx" && timeout 300 opencode run "$prompt") > "$log" 2>&1 </dev/null ;;
      esac
      used=$(grep -c -E '(^|[ "|;])afm ' "$log" || true)   # rough; score by reading the transcript
      printf '%-8s %-10s %-14s should=%-5s afm_calls=%s\n' "$h" "$setting" "$id" "$should" "$used"
    done
  done
done
echo "transcripts in $out; score them into RESULTS.md"
