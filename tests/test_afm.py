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


def run_afm(args, stdin="", env=None, tmp=None, stdin_tty=False):
    tmp = tmp or tempfile.mkdtemp()
    e = dict(os.environ)
    e["PATH"] = FAKEFM + os.pathsep + e.get("PATH", "")
    e["FAKEFM_LOG"] = os.path.join(tmp, "fm.log")
    e["TMPDIR"] = tmp
    e.update(env or {})
    if stdin_tty:
        import pty
        master, slave = pty.openpty()
        p = subprocess.run([sys.executable, AFM] + args, stdin=slave, capture_output=True, text=True, env=e)
        os.close(master)
        os.close(slave)
        return p
    return subprocess.run([sys.executable, AFM] + args, input=stdin, capture_output=True, text=True, env=e)


def fm_calls(tmp):
    path = os.path.join(tmp, "fm.log")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(line) for line in f]


def load_afm_module():
    mod = type(sys)("afm_mod")
    with open(AFM) as f:
        exec(compile(f.read(), AFM, "exec"), mod.__dict__)
    return mod


class ListTests(unittest.TestCase):
    def test_list_prints_presets_and_first_lines(self):
        p = run_afm(["--list"])
        self.assertEqual(p.returncode, 0, p.stderr)
        names = [line.split()[0] for line in p.stdout.splitlines()]
        self.assertEqual(names, ["classify", "commit-msg", "extract", "summarise"])
        self.assertIn("Summarise the input", p.stdout)

    def test_list_makes_no_fm_calls(self):
        tmp = tempfile.mkdtemp()
        run_afm(["--list"], tmp=tmp)
        self.assertEqual(fm_calls(tmp), [])


class UsageTests(unittest.TestCase):
    def assert_usage(self, args, stdin="hello", stdin_tty=False, needle=""):
        p = run_afm(args, stdin=stdin, stdin_tty=stdin_tty)
        self.assertEqual(p.returncode, 2, p.stderr)
        self.assertEqual(p.stdout, "")
        self.assertIn(needle, p.stderr)
        return p

    def test_unknown_preset(self):
        self.assert_usage(["nosuch"], needle="unknown preset")

    def test_no_job(self):
        self.assert_usage([], needle="usage")

    def test_ask_needs_instructions(self):
        self.assert_usage(["ask"], needle="instructions")

    def test_tty_stdin(self):
        self.assert_usage(["summarise"], stdin_tty=True, needle="reads its input from stdin")

    def test_empty_stdin(self):
        self.assert_usage(["summarise"], stdin="", needle="empty")

    def test_whitespace_only_stdin(self):
        self.assert_usage(["summarise"], stdin="  \n\n", needle="empty")

    def test_classify_needs_labels(self):
        self.assert_usage(["classify"], needle="--labels")

    def test_labels_empty_item(self):
        self.assert_usage(["classify", "--labels", "a,,b"], needle="empty label")

    def test_labels_duplicate(self):
        self.assert_usage(["classify", "--labels", "a,b,a"], needle="duplicate")

    def test_labels_on_other_preset(self):
        self.assert_usage(["summarise", "--labels", "a,b"], needle="--labels")

    def test_classify_rejects_schema(self):
        self.assert_usage(["classify", "--labels", "a,b", "--schema", "x.json"], needle="--schema")

    def test_extract_needs_schema(self):
        self.assert_usage(["extract"], needle="--schema")

    def test_schema_file_missing(self):
        self.assert_usage(["extract", "--schema", "/nonexistent.json"], needle="schema")

    def test_chunk_with_commit_msg(self):
        self.assert_usage(["commit-msg", "--chunk"], needle="--chunk")

    def test_usage_errors_make_no_fm_calls(self):
        tmp = tempfile.mkdtemp()
        run_afm(["classify"], stdin="x", tmp=tmp)
        self.assertEqual(fm_calls(tmp), [])


SANDBOX_MSG = "Error: The operation couldn\u2019t be completed. (ModelManagerServices.ModelManagerError error 1008.)\n"


class FmWrapperTests(unittest.TestCase):
    def test_fm_missing_is_exit_4(self):
        p = run_afm(["summarise"], stdin="hello", env={"PATH": "/nonexistent"})
        self.assertEqual(p.returncode, 4, p.stderr)
        self.assertEqual(p.stdout, "")
        self.assertIn("fm not found", p.stderr)

    def test_sandbox_on_count_tokens_is_exit_5_before_respond(self):
        tmp = tempfile.mkdtemp()
        p = run_afm(["summarise"], stdin="hello", tmp=tmp,
                    env={"FAKEFM_COUNT_EXIT": "1", "FAKEFM_COUNT_STDERR": SANDBOX_MSG})
        self.assertEqual(p.returncode, 5, p.stderr)
        self.assertIn("blocked by a sandbox", p.stderr)
        self.assertEqual([c["cmd"][0] for c in fm_calls(tmp)], ["count-tokens"])

    def test_other_count_failure_is_exit_1_with_stderr(self):
        p = run_afm(["summarise"], stdin="hello",
                    env={"FAKEFM_COUNT_EXIT": "1", "FAKEFM_COUNT_STDERR": "Error: something else\n"})
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn("something else", p.stderr)

    def test_count_includes_instructions(self):
        tmp = tempfile.mkdtemp()
        run_afm(["summarise"], stdin="hello", tmp=tmp)
        count = [c for c in fm_calls(tmp) if c["cmd"][0] == "count-tokens"][0]
        self.assertIn("-q", count["cmd"])
        self.assertIn("-i", count["cmd"])
        self.assertIn("Summarise the input", count["cmd"][count["cmd"].index("-i") + 1])
        self.assertEqual(count["stdin"], "hello")


class BudgetTests(unittest.TestCase):
    def test_over_budget_is_exit_6_with_numbers(self):
        tmp = tempfile.mkdtemp()
        p = run_afm(["summarise", "--budget", "100"], stdin="x" * 1000, tmp=tmp)
        self.assertEqual(p.returncode, 6, p.stderr)
        self.assertEqual(p.stdout, "")
        self.assertIn("budget is 100", p.stderr)
        self.assertIn("rerun with --chunk", p.stderr)
        self.assertEqual([c["cmd"][0] for c in fm_calls(tmp)], ["count-tokens"])

    def test_schema_counts_toward_budget(self):
        tmp = tempfile.mkdtemp()
        schema = os.path.join(tmp, "s.json")
        with open(schema, "w") as f:
            f.write("{" + "x" * 400 + "}")
        # input ~25 tokens + instructions, schema ~100 tokens, budget 110 -> over
        p = run_afm(["extract", "--schema", schema, "--budget", "110"], stdin="x" * 100, tmp=tmp)
        self.assertEqual(p.returncode, 6, p.stderr)
        counts = [c for c in fm_calls(tmp) if c["cmd"][0] == "count-tokens"]
        self.assertEqual(len(counts), 2)


class RespondTests(unittest.TestCase):
    def test_success_prints_answer_only(self):
        tmp = tempfile.mkdtemp()
        p = run_afm(["summarise"], stdin="hello world", tmp=tmp, env={"FAKEFM_RESPOND_STDOUT": "A summary.  \n\n"})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout, "A summary.\n")
        self.assertEqual(p.stderr, "")

    def test_respond_arguments(self):
        tmp = tempfile.mkdtemp()
        run_afm(["summarise", "--guardrails", "default", "--use-case", "content-tagging"], stdin="hello", tmp=tmp)
        r = [c for c in fm_calls(tmp) if c["cmd"][0] == "respond"][0]
        cmd = r["cmd"]
        for flag in ("--no-stream", "--greedy"):
            self.assertIn(flag, cmd)
        self.assertEqual(cmd[cmd.index("--guardrails") + 1], "default")
        self.assertEqual(cmd[cmd.index("--use-case") + 1], "content-tagging")
        self.assertIn("Summarise the input", cmd[cmd.index("-i") + 1])
        self.assertNotIn("--schema", cmd)
        self.assertEqual(r["stdin"], "hello")

    def test_default_guardrails_permissive(self):
        tmp = tempfile.mkdtemp()
        run_afm(["summarise"], stdin="hello", tmp=tmp)
        cmd = [c for c in fm_calls(tmp) if c["cmd"][0] == "respond"][0]["cmd"]
        self.assertEqual(cmd[cmd.index("--guardrails") + 1], "permissive-content-transformations")
        self.assertEqual(cmd[cmd.index("--use-case") + 1], "general")

    def test_refusal_is_exit_1_with_stderr(self):
        tmp = tempfile.mkdtemp()
        p = run_afm(["summarise"], stdin="hello", tmp=tmp, env={
            "FAKEFM_RESPOND_EXIT": "1",
            "FAKEFM_RESPOND_STDERR": "Error: The model's safety guardrails were triggered.\n"})
        self.assertEqual(p.returncode, 1)
        self.assertEqual(p.stdout, "")
        self.assertIn("safety guardrails", p.stderr)
        self.assertEqual([c["cmd"][0] for c in fm_calls(tmp)], ["count-tokens", "respond", "available"])

    def test_respond_failure_with_model_unavailable_is_exit_4(self):
        p = run_afm(["summarise"], stdin="hello", env={
            "FAKEFM_RESPOND_EXIT": "1", "FAKEFM_RESPOND_STDERR": "Error: x\n",
            "FAKEFM_AVAILABLE_EXIT": "1", "FAKEFM_AVAILABLE_STDERR": "Model not available\n"})
        self.assertEqual(p.returncode, 4, p.stderr)
        self.assertIn("not available", p.stderr)

    def test_sandbox_on_respond_is_exit_5(self):
        p = run_afm(["summarise"], stdin="hello", env={"FAKEFM_COUNT": "10",
                    "FAKEFM_RESPOND_EXIT": "1", "FAKEFM_RESPOND_STDERR": SANDBOX_MSG})
        self.assertEqual(p.returncode, 5, p.stderr)

    def test_timeout_is_exit_1_and_kills_child(self):
        tmp = tempfile.mkdtemp()
        p = run_afm(["summarise", "--timeout", "0.5"], stdin="hello", tmp=tmp, env={"FAKEFM_RESPOND_DELAY": "5"})
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn("timed out after 0.5 s", p.stderr)
        pid = [c for c in fm_calls(tmp) if c["cmd"][0] == "respond"][0]["pid"]
        self.assert_gone(pid)

    def assert_gone(self, pid):
        for _ in range(50):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.1)
        self.fail("fm child %d still alive" % pid)


class SignalTests(unittest.TestCase):
    def test_sigterm_kills_child_and_removes_temp_schema(self):
        tmp = tempfile.mkdtemp()
        e = dict(os.environ)
        e["PATH"] = FAKEFM + os.pathsep + e.get("PATH", "")
        e["FAKEFM_LOG"] = os.path.join(tmp, "fm.log")
        e["TMPDIR"] = tmp
        e["FAKEFM_RESPOND_DELAY"] = "10"
        proc = subprocess.Popen([sys.executable, AFM, "classify", "--labels", "a,b"], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=e)
        proc.stdin.write("hello")
        proc.stdin.close()
        for _ in range(50):
            if any(c["cmd"][0] == "respond" for c in fm_calls(tmp)):
                break
            time.sleep(0.1)
        child = [c for c in fm_calls(tmp) if c["cmd"][0] == "respond"][0]["pid"]
        self.assertTrue(any(n.endswith(".json") for n in os.listdir(tmp)), "temp schema should exist while running")
        proc.send_signal(signal.SIGTERM)
        out, err = proc.communicate(timeout=5)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(out, "")
        self.assertIn("interrupted", err)
        RespondTests.assert_gone(self, child)
        self.assertFalse(any(n.endswith(".json") for n in os.listdir(tmp)), "temp schema should be removed")


if __name__ == "__main__":
    unittest.main()
