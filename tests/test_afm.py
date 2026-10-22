import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AFM = os.path.join(ROOT, "scripts", "afm")
FAKEFM = os.path.join(ROOT, "tests", "fakefm")
SANDBOX_MSG = "Error: The operation couldn’t be completed. (ModelManagerServices.ModelManagerError error 1008.)\n"

GOOD_SLUGIFY = '''import re

def slugify(title):
    title = re.sub(r"[^a-z0-9]+", "-", title.lower())
    return title.strip("-")
'''
BAD_SLUGIFY = '''def slugify(title):
    return title
'''
SLUGIFY_TESTS = '''import unittest
from util import slugify
class T(unittest.TestCase):
    def test_basic(self): self.assertEqual(slugify("Hello, World!"), "hello-world")
    def test_empty(self): self.assertEqual(slugify("!!!"), "")
'''
SLUGIFY_SPEC = "Write a Python function `slugify(title)` that lowercases, replaces runs of non-alphanumerics with one hyphen and strips hyphens."


class Project(object):
    """A throwaway project directory with a steps dir, a fake-fm reply sequence and a log."""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="afm-proj-")
        self.steps = os.path.join(self.dir, "steps")
        self.seq = os.path.join(self.dir, "seq")
        os.makedirs(self.steps)
        os.makedirs(self.seq)
        self.replies = 0

    def write(self, rel, content):
        path = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        return path

    def read(self, rel):
        with open(os.path.join(self.dir, rel)) as f:
            return f.read()

    def exists(self, rel):
        return os.path.exists(os.path.join(self.dir, rel))

    def step(self, name, spec=SLUGIFY_SPEC, file="util.py", test="python3 -m unittest test_util", context=None, header_extra=""):
        lines = []
        if file is not None:
            lines.append("file: %s" % file)
        if test is not None:
            lines.append("test: %s" % test)
        if context:
            lines.append("context: %s" % context)
        body = "\n".join(lines) + header_extra + "\n---\n" + spec + "\n"
        return self.write("steps/%s.md" % name, body)

    def reply(self, text):
        self.replies += 1
        with open(os.path.join(self.seq, str(self.replies)), "w") as f:
            f.write(text)

    def run(self, args, env=None, stdin_tty=False):
        e = dict(os.environ)
        e["PATH"] = FAKEFM + os.pathsep + e.get("PATH", "")
        e["FAKEFM_LOG"] = os.path.join(self.dir, "fm.log")
        e["FAKEFM_RESPOND_SEQ"] = self.seq
        e["TMPDIR"] = self.dir
        e.update(env or {})
        return subprocess.run([sys.executable, AFM] + args, cwd=self.dir, capture_output=True, text=True, env=e,
                              stdin=subprocess.DEVNULL, timeout=120)

    def fm_calls(self):
        path = os.path.join(self.dir, "fm.log")
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return [json.loads(line) for line in f]

    def responds(self):
        return [c for c in self.fm_calls() if c["cmd"][0] == "respond"]


def instr_of(cmd):
    for a in cmd:
        if a.startswith("--instructions="):
            return a[len("--instructions="):]
    return None


class UsageTests(unittest.TestCase):
    def assert_usage(self, p, needle):
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertEqual(p.stdout, "")
        self.assertIn(needle, p.stderr)

    def test_no_command(self):
        self.assert_usage(Project().run([]), "usage")

    def test_missing_dir(self):
        self.assert_usage(Project().run(["run", "nosuch"]), "nosuch")

    def test_empty_dir(self):
        pr = Project()
        self.assert_usage(pr.run(["run", "steps"]), "no step files")

    def test_step_without_file_key(self):
        pr = Project()
        pr.step("01-a", file=None)
        self.assert_usage(pr.run(["run", "steps"]), "file:")

    def test_step_without_test_key(self):
        pr = Project()
        pr.step("01-a", test=None)
        self.assert_usage(pr.run(["run", "steps"]), "test:")

    def test_step_without_separator(self):
        pr = Project()
        pr.write("steps/01-a.md", "file: util.py\ntest: true\nno separator here\n")
        self.assert_usage(pr.run(["run", "steps"]), "---")

    def test_step_with_empty_spec(self):
        pr = Project()
        pr.write("steps/01-a.md", "file: util.py\ntest: true\n---\n\n")
        self.assert_usage(pr.run(["run", "steps"]), "empty")

    def test_unknown_header_key(self):
        pr = Project()
        pr.step("01-a", header_extra="\nbogus: 1")
        self.assert_usage(pr.run(["run", "steps"]), "bogus")

    def test_missing_context_file(self):
        pr = Project()
        pr.step("01-a", context="nothere.py")
        self.assert_usage(pr.run(["run", "steps"]), "nothere.py")

    def test_context_produced_by_an_earlier_step_is_accepted(self):
        pr = Project()
        pr.write("test_util.py", SLUGIFY_TESTS)
        pr.step("01-a", file="first.py", test="true")
        pr.step("02-b", file="util.py", context="first.py")
        pr.reply("# first\n")
        pr.reply(GOOD_SLUGIFY)
        p = pr.run(["run", "steps"])
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("# first", pr.responds()[1]["stdin"])

    def test_context_from_a_later_step_is_rejected(self):
        pr = Project()
        pr.step("01-a", file="util.py", context="later.py")
        pr.step("02-b", file="later.py", test="true")
        self.assert_usage(pr.run(["run", "steps"]), "later.py")

    def test_help_usage_line_is_not_doubled(self):
        p = Project().run(["--help"])
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(p.stdout.startswith("usage: afm "), p.stdout[:60])
        self.assertNotIn("usage: usage:", p.stdout)
        self.assertIn("--retries", p.stdout)
        self.assertIn("file:", p.stdout)

    def test_bad_retries(self):
        pr = Project()
        pr.step("01-a")
        self.assert_usage(pr.run(["run", "steps", "--retries", "-1"]), "--retries")

    def test_usage_errors_make_no_fm_calls(self):
        pr = Project()
        pr.step("01-a", file=None)
        pr.run(["run", "steps"])
        self.assertEqual(pr.fm_calls(), [])

    def test_all_steps_validated_before_any_run(self):
        pr = Project()
        pr.step("01-a")
        pr.step("02-b", test=None)
        pr.reply(GOOD_SLUGIFY)
        p = pr.run(["run", "steps"])
        self.assertEqual(p.returncode, 2, p.stderr)
        self.assertEqual(pr.fm_calls(), [])


class SingleStepTests(unittest.TestCase):
    def test_pass_first_try(self):
        pr = Project()
        pr.write("test_util.py", SLUGIFY_TESTS)
        pr.step("01-slugify")
        pr.reply(GOOD_SLUGIFY)
        p = pr.run(["run", "steps"])
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(pr.read("util.py"), GOOD_SLUGIFY)
        self.assertIn("01-slugify", p.stdout)
        self.assertIn("pass", p.stdout)
        self.assertEqual(p.stderr, "")
        self.assertEqual(len(pr.responds()), 1)

    def test_prompt_has_spec_not_tests(self):
        pr = Project()
        pr.write("test_util.py", SLUGIFY_TESTS)
        pr.step("01-slugify")
        pr.reply(GOOD_SLUGIFY)
        pr.run(["run", "steps"])
        r = pr.responds()[0]
        self.assertIn(SLUGIFY_SPEC, r["stdin"])
        self.assertNotIn("assertEqual", r["stdin"])
        self.assertIn("util.py", instr_of(r["cmd"]))
        self.assertIn("--no-stream", r["cmd"])
        self.assertIn("--greedy", r["cmd"])
        self.assertNotIn("Current contents", r["stdin"])

    def test_existing_file_is_shown_for_edit(self):
        pr = Project()
        pr.write("test_util.py", SLUGIFY_TESTS)
        pr.write("util.py", "# old\n")
        pr.step("01-slugify")
        pr.reply(GOOD_SLUGIFY)
        pr.run(["run", "steps"])
        stdin = pr.responds()[0]["stdin"]
        self.assertIn("Current contents of util.py", stdin)
        self.assertIn("# old", stdin)

    def test_context_files_are_shown(self):
        pr = Project()
        pr.write("test_util.py", SLUGIFY_TESTS)
        pr.write("types.py", "class Thing: pass\n")
        pr.write("errors.py", "class Oops(Exception): pass\n")
        pr.step("01-slugify", context="types.py, errors.py")
        pr.reply(GOOD_SLUGIFY)
        pr.run(["run", "steps"])
        stdin = pr.responds()[0]["stdin"]
        self.assertIn("Reference only, do not modify: types.py", stdin)
        self.assertIn("class Thing", stdin)
        self.assertIn("class Oops", stdin)

    def test_fences_are_stripped(self):
        pr = Project()
        pr.write("test_util.py", SLUGIFY_TESTS)
        pr.step("01-slugify")
        pr.reply("```python\n" + GOOD_SLUGIFY + "```\n")
        p = pr.run(["run", "steps"])
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(pr.read("util.py"), GOOD_SLUGIFY)

    def test_file_in_subdirectory_is_created(self):
        pr = Project()
        pr.write("test_util.py", SLUGIFY_TESTS.replace("from util", "from pkg.util"))
        pr.write("pkg/__init__.py", "")
        pr.step("01-slugify", file="pkg/util.py")
        pr.reply(GOOD_SLUGIFY)
        p = pr.run(["run", "steps"])
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertTrue(pr.exists("pkg/util.py"))

    def test_json_report(self):
        pr = Project()
        pr.write("test_util.py", SLUGIFY_TESTS)
        pr.step("01-slugify")
        pr.reply(GOOD_SLUGIFY)
        p = pr.run(["run", "steps", "--json"])
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        d = json.loads(p.stdout)
        self.assertIsNone(d["failed"])
        self.assertEqual(d["steps"][0]["id"], "01-slugify")
        self.assertEqual(d["steps"][0]["file"], "util.py")
        self.assertEqual(d["steps"][0]["result"], "pass")
        self.assertEqual(d["steps"][0]["attempts"], 1)
        self.assertIn("seconds", d["steps"][0])

    def test_step_command_runs_one_file(self):
        pr = Project()
        pr.write("test_util.py", SLUGIFY_TESTS)
        path = pr.step("01-slugify")
        pr.reply(GOOD_SLUGIFY)
        p = pr.run(["step", path])
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(pr.read("util.py"), GOOD_SLUGIFY)

    def test_steps_run_in_filename_order(self):
        pr = Project()
        pr.step("02-second", spec="SECOND", file="second.py", test="true")
        pr.step("01-first", spec="FIRST", file="first.py", test="true")
        pr.step("10-tenth", spec="TENTH", file="tenth.py", test="true")
        for _ in range(3):
            pr.reply("x = 1\n")
        p = pr.run(["run", "steps"])
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        specs = [r["stdin"] for r in pr.responds()]
        self.assertIn("FIRST", specs[0])
        self.assertIn("SECOND", specs[1])
        self.assertIn("TENTH", specs[2])
        self.assertLess(p.stdout.index("01-first"), p.stdout.index("02-second"))


class RetryAndFailureTests(unittest.TestCase):
    def test_fail_then_pass_on_retry(self):
        pr = Project()
        pr.write("test_util.py", SLUGIFY_TESTS)
        pr.step("01-slugify")
        pr.reply(BAD_SLUGIFY)
        pr.reply(GOOD_SLUGIFY)
        p = pr.run(["run", "steps"])
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(pr.read("util.py"), GOOD_SLUGIFY)
        self.assertIn("2", p.stdout.splitlines()[1])
        retry = pr.responds()[1]["stdin"]
        self.assertIn("Your previous implementation", retry)
        self.assertIn("return title", retry)
        self.assertIn("test_basic", retry)
        self.assertIn(SLUGIFY_SPEC, retry)

    def test_fail_after_retries_restores_file_and_saves_attempt(self):
        pr = Project()
        pr.write("test_util.py", SLUGIFY_TESTS)
        pr.write("util.py", "# original\n")
        pr.step("01-slugify")
        pr.reply(BAD_SLUGIFY)
        pr.reply(BAD_SLUGIFY)
        p = pr.run(["run", "steps"])
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertEqual(pr.read("util.py"), "# original\n")
        self.assertEqual(pr.read("util.py.afm-failed"), BAD_SLUGIFY)
        self.assertIn("FAIL", p.stdout)
        self.assertIn("failed after 2 attempts", p.stdout)
        self.assertIn("python3 -m unittest test_util", p.stdout)
        self.assertIn("test_basic", p.stdout)
        self.assertIn("util.py.afm-failed", p.stdout)
        self.assertIn("restored", p.stdout)

    def test_created_file_is_deleted_on_final_failure(self):
        pr = Project()
        pr.write("test_util.py", SLUGIFY_TESTS)
        pr.step("01-slugify")
        pr.reply(BAD_SLUGIFY)
        pr.reply(BAD_SLUGIFY)
        p = pr.run(["run", "steps"])
        self.assertEqual(p.returncode, 1)
        self.assertFalse(pr.exists("util.py"))
        self.assertTrue(pr.exists("util.py.afm-failed"))
        self.assertIn("removed", p.stdout)

    def test_zero_retries(self):
        pr = Project()
        pr.write("test_util.py", SLUGIFY_TESTS)
        pr.step("01-slugify")
        pr.reply(BAD_SLUGIFY)
        p = pr.run(["run", "steps", "--retries", "0"])
        self.assertEqual(p.returncode, 1)
        self.assertEqual(len(pr.responds()), 1)
        self.assertIn("failed after 1 attempt", p.stdout)

    def test_stops_at_first_failure(self):
        pr = Project()
        pr.write("test_util.py", SLUGIFY_TESTS)
        pr.step("01-a")
        pr.step("02-b", spec="SECOND", file="b.py", test="python3 -c \"import b; assert b.OK\"")
        pr.step("03-c", spec="THIRD", file="c.py", test="true")
        pr.reply(GOOD_SLUGIFY)
        pr.reply("OK = False\n")
        pr.reply("OK = False\n")
        pr.reply("x = 1\n")
        p = pr.run(["run", "steps"])
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertEqual(len(pr.responds()), 3)
        self.assertIn("03-c", p.stdout)
        self.assertIn("skipped", p.stdout)

    def test_json_report_on_failure(self):
        pr = Project()
        pr.write("test_util.py", SLUGIFY_TESTS)
        pr.step("01-a")
        pr.step("02-b", spec="SECOND", file="b.py", test="true")
        pr.reply(BAD_SLUGIFY)
        pr.reply(BAD_SLUGIFY)
        p = pr.run(["run", "steps", "--json"])
        self.assertEqual(p.returncode, 1)
        d = json.loads(p.stdout)
        self.assertEqual(d["failed"]["id"], "01-a")
        self.assertIn("test_basic", d["failed"]["output"])
        self.assertEqual(d["failed"]["test"], "python3 -m unittest test_util")
        self.assertTrue(d["failed"]["saved"].endswith("util.py.afm-failed"))
        self.assertEqual([s["result"] for s in d["steps"]], ["FAIL", "skipped"])

    def test_empty_model_output_counts_as_failure(self):
        pr = Project()
        pr.write("test_util.py", SLUGIFY_TESTS)
        pr.step("01-slugify")
        pr.reply("   \n")
        pr.reply(GOOD_SLUGIFY)
        p = pr.run(["run", "steps"])
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("2", p.stdout.splitlines()[1])

    def test_fm_refusal_fails_the_step(self):
        pr = Project()
        pr.write("test_util.py", SLUGIFY_TESTS)
        pr.step("01-slugify")
        p = pr.run(["run", "steps"], env={"FAKEFM_RESPOND_SEQ": "", "FAKEFM_RESPOND_EXIT": "1",
                                          "FAKEFM_RESPOND_STDERR": "Error: The model's safety guardrails were triggered.\n"})
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("01-slugify", p.stdout)
        self.assertIn("guardrails", p.stdout)

    def test_sandbox_is_exit_5(self):
        pr = Project()
        pr.write("test_util.py", SLUGIFY_TESTS)
        pr.step("01-slugify")
        p = pr.run(["run", "steps"], env={"FAKEFM_COUNT_EXIT": "1", "FAKEFM_COUNT_STDERR": SANDBOX_MSG})
        self.assertEqual(p.returncode, 5, p.stdout + p.stderr)
        self.assertIn("sandbox", p.stderr)

    def test_fm_missing_is_exit_4(self):
        pr = Project()
        pr.step("01-slugify")
        p = pr.run(["run", "steps"], env={"PATH": "/nonexistent"})
        self.assertEqual(p.returncode, 4, p.stderr)

    def test_over_budget_names_the_step(self):
        pr = Project()
        pr.write("test_util.py", SLUGIFY_TESTS)
        pr.step("01-big", spec="x" * 2000)
        p = pr.run(["run", "steps", "--budget", "100"])
        self.assertEqual(p.returncode, 6, p.stdout + p.stderr)
        self.assertIn("01-big", p.stderr)
        self.assertIn("budget is 100", p.stderr)
        self.assertIn("split the step", p.stderr)
        self.assertEqual(pr.responds(), [])

    def test_timeout_fails_the_step(self):
        pr = Project()
        pr.write("test_util.py", SLUGIFY_TESTS)
        pr.step("01-slugify")
        p = pr.run(["run", "steps", "--timeout", "0.5", "--retries", "0"], env={"FAKEFM_RESPOND_DELAY": "5", "FAKEFM_RESPOND_SEQ": ""})
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("timed out", p.stdout)

    def test_test_command_failure_output_is_shown(self):
        pr = Project()
        pr.step("01-slugify", test="python3 -c \"import sys; print('boom'); sys.exit(3)\"")
        pr.reply(GOOD_SLUGIFY)
        pr.reply(GOOD_SLUGIFY)
        p = pr.run(["run", "steps"])
        self.assertEqual(p.returncode, 1)
        self.assertIn("boom", p.stdout)


class RerunTests(unittest.TestCase):
    def test_step_whose_test_already_passes_is_skipped(self):
        pr = Project()
        pr.write("test_util.py", SLUGIFY_TESTS)
        pr.write("util.py", GOOD_SLUGIFY)
        pr.step("01-slugify")
        p = pr.run(["run", "steps"])
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(pr.responds(), [])
        self.assertIn("already", p.stdout)
        self.assertEqual(json.loads(pr.run(["run", "steps", "--json"]).stdout)["steps"][0]["attempts"], 0)

    def test_rerun_after_fix_skips_passed_steps(self):
        pr = Project()
        pr.write("test_util.py", SLUGIFY_TESTS)
        pr.step("01-a")
        pr.step("02-b", file="other.py", test="python3 -c \"import other; assert other.X == 1\"")
        pr.reply(GOOD_SLUGIFY)
        pr.reply("X = 2\n")
        pr.reply("X = 2\n")
        p = pr.run(["run", "steps"])
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        pr.reply("X = 1\n")
        p = pr.run(["run", "steps"])
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(len(pr.responds()), 4, "step 01 must not be regenerated on the rerun")
        self.assertEqual(pr.read("other.py"), "X = 1\n")

    def test_hand_written_step_is_left_alone(self):
        pr = Project()
        pr.write("test_util.py", SLUGIFY_TESTS)
        pr.write("util.py", GOOD_SLUGIFY + "# by hand\n")
        pr.step("01-slugify")
        pr.run(["run", "steps"])
        self.assertIn("# by hand", pr.read("util.py"))


class ReportDetailTests(unittest.TestCase):
    def test_retried_pass_reports_why_the_first_attempt_failed(self):
        pr = Project()
        pr.write("test_util.py", SLUGIFY_TESTS)
        pr.step("01-slugify")
        pr.reply(BAD_SLUGIFY)
        pr.reply(GOOD_SLUGIFY)
        p = pr.run(["run", "steps"])
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("attempt 1 failed", p.stdout)
        self.assertIn("test_basic", p.stdout)
        d = json.loads(pr.run(["run", "steps", "--json"]).stdout)
        self.assertEqual(d["steps"][0]["result"], "pass")

    def test_stale_failed_attempt_is_removed_on_pass(self):
        pr = Project()
        pr.write("test_util.py", SLUGIFY_TESTS)
        pr.write("util.py.afm-failed", "old\n")
        pr.write("util.py.afm-failed.log", "old\n")
        pr.step("01-slugify")
        pr.reply(GOOD_SLUGIFY)
        p = pr.run(["run", "steps"])
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertFalse(pr.exists("util.py.afm-failed"))
        self.assertFalse(pr.exists("util.py.afm-failed.log"))

    def test_failure_keeps_full_log_and_shows_head_and_tail(self):
        pr = Project()
        lines = "\\n".join("line %03d" % i for i in range(200))
        pr.step("01-x", test="python3 -c \"print('%s'); raise SystemExit(1)\"" % lines)
        pr.reply("x = 1\n")
        pr.reply("x = 1\n")
        p = pr.run(["run", "steps"])
        self.assertEqual(p.returncode, 1)
        self.assertIn("line 000", p.stdout)
        self.assertIn("line 199", p.stdout)
        self.assertIn("lines omitted", p.stdout)
        self.assertIn("line 100", pr.read("util.py.afm-failed.log"))
        self.assertIn("util.py.afm-failed.log", p.stdout)

    def test_removed_message_says_it_did_not_exist(self):
        pr = Project()
        pr.write("test_util.py", SLUGIFY_TESTS)
        pr.step("01-slugify")
        pr.reply(BAD_SLUGIFY)
        pr.reply(BAD_SLUGIFY)
        p = pr.run(["run", "steps"])
        self.assertIn("did not exist before", p.stdout)


class SignalTests(unittest.TestCase):
    def test_sigterm_kills_child(self):
        pr = Project()
        pr.write("test_util.py", SLUGIFY_TESTS)
        pr.step("01-slugify")
        e = dict(os.environ)
        e["PATH"] = FAKEFM + os.pathsep + e.get("PATH", "")
        e["FAKEFM_LOG"] = os.path.join(pr.dir, "fm.log")
        e["FAKEFM_RESPOND_DELAY"] = "10"
        proc = subprocess.Popen([sys.executable, AFM, "run", "steps"], cwd=pr.dir, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=e)
        for _ in range(50):
            if pr.responds():
                break
            time.sleep(0.1)
        child = pr.responds()[0]["pid"]
        proc.send_signal(signal.SIGTERM)
        out, err = proc.communicate(timeout=5)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("interrupted", err)
        for _ in range(50):
            try:
                os.kill(child, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            self.fail("fm child still alive")


def real_model_works():
    try:
        if subprocess.run(["fm", "available"], capture_output=True).returncode != 0:
            return False
        return subprocess.run(["fm", "respond", "--no-stream", "hi"], capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


@unittest.skipUnless(real_model_works(), "on-device model not usable here")
class IntegrationTests(unittest.TestCase):
    def test_slugify_step_on_real_model(self):
        pr = Project()
        pr.write("test_util.py", SLUGIFY_TESTS)
        pr.step("01-slugify", spec=(
            "Write a Python function `slugify(title)`. Lowercase the string, replace every run of characters that are "
            "not ASCII letters or digits with a single hyphen, and strip leading and trailing hyphens. "
            "Examples: slugify(\"Hello, World!\") == \"hello-world\"; slugify(\"!!!\") == \"\"."))
        e = dict(os.environ)
        p = subprocess.run([AFM, "run", "steps"], cwd=pr.dir, capture_output=True, text=True, env=e, timeout=300)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("pass", p.stdout)


if __name__ == "__main__":
    unittest.main()
