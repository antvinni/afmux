import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "hooks", "nudge-large-output")


def run_hook(payload, env=None):
    e = dict(os.environ)
    e.update(env or {})
    return subprocess.run([sys.executable, HOOK], input=json.dumps(payload), capture_output=True, text=True, env=e)


class HookTests(unittest.TestCase):
    def test_small_output_is_silent(self):
        p = run_hook({"tool_name": "Bash", "tool_response": {"stdout": "ok", "stderr": ""}})
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stdout, "")

    def test_large_output_adds_context(self):
        p = run_hook({"tool_name": "Bash", "tool_response": {"stdout": "x" * 20000, "stderr": ""}})
        self.assertEqual(p.returncode, 0)
        out = json.loads(p.stdout)
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "PostToolUse")
        self.assertIn("5000 tokens", ctx)
        self.assertIn("afm", ctx)

    def test_threshold_env(self):
        p = run_hook({"tool_name": "Bash", "tool_response": "y" * 800}, env={"AFMUX_NUDGE_TOKENS": "100"})
        self.assertIn("afm", p.stdout)

    def test_other_tools_ignored(self):
        p = run_hook({"tool_name": "Read", "tool_response": "x" * 20000})
        self.assertEqual(p.stdout, "")

    def test_bad_json_is_silent(self):
        p = subprocess.run([sys.executable, HOOK], input="not json", capture_output=True, text=True)
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stdout, "")


if __name__ == "__main__":
    unittest.main()
