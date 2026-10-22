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


def instr_of(cmd):
    for a in cmd:
        if a.startswith("--instructions="):
            return a[len("--instructions="):]
    return None


def good_schema(tmp, name="s.json"):
    path = os.path.join(tmp, name)
    with open(path, "w") as f:
        json.dump({"title": "T", "type": "object", "properties": {"a": {"type": "integer"}},
                   "required": ["a"], "x-order": ["a"], "additionalProperties": False}, f)
    return path


def load_afm_module():
    mod = type(sys)("afm_mod")
    mod.__file__ = AFM
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
        self.assertIn("Summarise the input", instr_of(count["cmd"]))
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
            json.dump({"x-order": ["a"], "description": "x" * 400}, f)
        # input ~25 tokens + instructions ~40, schema ~110 tokens, budget 120 -> over
        p = run_afm(["extract", "--schema", schema, "--budget", "120"], stdin="x" * 100, tmp=tmp)
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
        self.assertIn("Summarise the input", instr_of(cmd))
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


class SchemaTests(unittest.TestCase):
    def test_classify_schema_fields(self):
        tmp = tempfile.mkdtemp()
        run_afm(["classify", "--labels", "bug, feature ,question"], stdin="x", tmp=tmp,
                env={"FAKEFM_RESPOND_STDOUT": '{"label": "bug"}'})
        r = [c for c in fm_calls(tmp) if c["cmd"][0] == "respond"][0]
        path = r["cmd"][r["cmd"].index("--schema") + 1]
        s = json.loads(r["schema"])
        self.assertEqual(s, {
            "title": "Classification", "type": "object",
            "properties": {"label": {"type": "string", "enum": ["bug", "feature", "question"]}},
            "required": ["label"], "x-order": ["label"], "additionalProperties": False})
        self.assertTrue(path.endswith(".json"))
        self.assertFalse(os.path.exists(path), "temp schema removed after exit")

    def test_classify_instructions_have_labels(self):
        tmp = tempfile.mkdtemp()
        run_afm(["classify", "--labels", "bug,feature"], stdin="x", tmp=tmp, env={"FAKEFM_RESPOND_STDOUT": '{"label": "bug"}'})
        cmd = [c for c in fm_calls(tmp) if c["cmd"][0] == "respond"][0]["cmd"]
        self.assertIn("bug, feature", instr_of(cmd))

    def test_classify_output_is_compact_json(self):
        p = run_afm(["classify", "--labels", "bug,feature"], stdin="x", env={"FAKEFM_RESPOND_STDOUT": '{ "label" : "feature" }'})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout, '{"label":"feature"}\n')

    def test_classify_label_outside_list_is_exit_3(self):
        p = run_afm(["classify", "--labels", "bug,feature"], stdin="x", env={"FAKEFM_RESPOND_STDOUT": '{"label": "other"}'})
        self.assertEqual(p.returncode, 3)
        self.assertEqual(p.stdout, "")
        self.assertIn("other", p.stderr)

    def test_invalid_json_is_exit_3_with_raw_on_stderr(self):
        p = run_afm(["classify", "--labels", "bug,feature"], stdin="x", env={"FAKEFM_RESPOND_STDOUT": "not json {"})
        self.assertEqual(p.returncode, 3)
        self.assertEqual(p.stdout, "")
        self.assertIn("not json {", p.stderr)

    def test_extract_uses_given_schema_and_compacts(self):
        tmp = tempfile.mkdtemp()
        schema = good_schema(tmp)
        p = run_afm(["extract", "--schema", schema], stdin="x", tmp=tmp, env={"FAKEFM_RESPOND_STDOUT": '{"a": 1,\n "b": "two"}'})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout, '{"a":1,"b":"two"}\n')
        cmd = [c for c in fm_calls(tmp) if c["cmd"][0] == "respond"][0]["cmd"]
        self.assertEqual(cmd[cmd.index("--schema") + 1], schema)
        self.assertTrue(os.path.exists(schema), "user schema must not be deleted")

    def test_ask_with_schema(self):
        tmp = tempfile.mkdtemp()
        schema = good_schema(tmp)
        p = run_afm(["ask", "Extract.", "--schema", schema], stdin="x", tmp=tmp, env={"FAKEFM_RESPOND_STDOUT": '{"k": true}'})
        self.assertEqual(p.stdout, '{"k":true}\n')


class ChunkTests(unittest.TestCase):
    # ask "S." instructions are 2 bytes -> count = ceil((len+2)/4)
    def test_fits_in_one_piece_still_uses_chunk_format(self):
        p = run_afm(["ask", "S.", "--chunk"], stdin="hello", env={"FAKEFM_RESPOND_STDOUT": "ans"})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout, "[1/1]\nans\n")

    def test_splits_at_blank_lines_and_keeps_order(self):
        tmp = tempfile.mkdtemp()
        text = "\n\n".join(["A" * 100, "B" * 100, "C" * 100])
        # each paragraph ~26 tokens; budget 60 -> 2 per piece max
        p = run_afm(["ask", "S.", "--chunk", "--budget", "60"], stdin=text, tmp=tmp, env={"FAKEFM_RESPOND_MODE": "first-line"})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout, "[1/2]\n%s\n[2/2]\n%s\n" % ("A" * 100, "C" * 100))
        responds = [c for c in fm_calls(tmp) if c["cmd"][0] == "respond"]
        self.assertEqual(responds[0]["stdin"], "A" * 100 + "\n\n" + "B" * 100)
        self.assertEqual(responds[1]["stdin"], "C" * 100)

    def test_long_paragraph_splits_at_lines(self):
        tmp = tempfile.mkdtemp()
        text = "\n".join(["L%d" % i + "x" * 98 for i in range(4)])  # one paragraph, 4 lines of 100 bytes
        p = run_afm(["ask", "S.", "--chunk", "--budget", "60"], stdin=text, tmp=tmp, env={"FAKEFM_RESPOND_MODE": "first-line"})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(p.stdout.startswith("[1/2]\nL0"), p.stdout)
        responds = [c for c in fm_calls(tmp) if c["cmd"][0] == "respond"]
        self.assertEqual(len(responds), 2)
        self.assertEqual(responds[0]["stdin"].count("\n"), 1)

    def test_single_line_over_budget_is_exit_6(self):
        tmp = tempfile.mkdtemp()
        text = "short\n\n" + "y" * 1000
        p = run_afm(["ask", "S.", "--chunk", "--budget", "60"], stdin=text, tmp=tmp)
        self.assertEqual(p.returncode, 6, p.stderr)
        self.assertEqual(p.stdout, "")
        self.assertIn("line 3 is", p.stderr)
        self.assertIn("budget is 60", p.stderr)
        self.assertEqual([c for c in fm_calls(tmp) if c["cmd"][0] == "respond"], [])

    def test_too_many_chunks_is_exit_6_before_respond(self):
        tmp = tempfile.mkdtemp()
        text = "\n\n".join(["P" * 100] * 5)
        p = run_afm(["ask", "S.", "--chunk", "--budget", "30", "--max-chunks", "3"], stdin=text, tmp=tmp)
        self.assertEqual(p.returncode, 6, p.stderr)
        self.assertIn("input needs more than 3 chunks, max is 3", p.stderr)
        self.assertEqual([c for c in fm_calls(tmp) if c["cmd"][0] == "respond"], [])

    def test_middle_piece_failure_stops_with_prefix_and_empty_stdout(self):
        tmp = tempfile.mkdtemp()
        text = "\n\n".join(["P" * 100] * 3)
        p = run_afm(["ask", "S.", "--chunk", "--budget", "30"], stdin=text, tmp=tmp, env={
            "FAKEFM_RESPOND_FAIL_ON_CALL": "2", "FAKEFM_RESPOND_EXIT": "1",
            "FAKEFM_RESPOND_STDERR": "Error: The model's safety guardrails were triggered.\n"})
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertEqual(p.stdout, "")
        self.assertIn("chunk 2/3: ", p.stderr)
        self.assertIn("guardrails", p.stderr)
        self.assertEqual(len([c for c in fm_calls(tmp) if c["cmd"][0] == "respond"]), 2)

    def test_schema_chunks_are_json_lines(self):
        tmp = tempfile.mkdtemp()
        text = "\n\n".join(["P" * 100] * 2)
        # classify instructions ~38 tokens + schema ~38 tokens + one paragraph ~26 -> 102; two paragraphs -> 128
        p = run_afm(["classify", "--labels", "a,b", "--chunk", "--budget", "115"], stdin=text, tmp=tmp,
                    env={"FAKEFM_RESPOND_STDOUT": '{"label": "a"}'})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout, '{"label":"a"}\n{"label":"a"}\n')

    def test_over_budget_without_chunk_still_exit_6(self):
        p = run_afm(["ask", "S.", "--budget", "10"], stdin="z" * 100)
        self.assertEqual(p.returncode, 6)


class ReviewFixTests(unittest.TestCase):
    """Regressions from the PR #1 review."""

    def test_leading_blank_lines_do_not_make_an_empty_chunk(self):
        tmp = tempfile.mkdtemp()
        p = run_afm(["ask", "S.", "--chunk", "--budget", "60"], stdin="\n\n" + "A" * 100 + "\n\n" + "B" * 100 + "\n",
                    tmp=tmp, env={"FAKEFM_RESPOND_MODE": "first-line"})
        self.assertEqual(p.returncode, 0, p.stderr)
        responds = [c["stdin"] for c in fm_calls(tmp) if c["cmd"][0] == "respond"]
        self.assertEqual(responds, ["A" * 100 + "\n\n" + "B" * 100])
        self.assertEqual(p.stdout, "[1/1]\n%s\n" % ("A" * 100))

    def test_whitespace_only_paragraph_is_dropped(self):
        tmp = tempfile.mkdtemp()
        p = run_afm(["ask", "S.", "--chunk", "--budget", "60"], stdin="A" * 100 + "\n\n \n\n" + "B" * 100,
                    tmp=tmp, env={"FAKEFM_RESPOND_MODE": "first-line"})
        self.assertEqual(p.returncode, 0, p.stderr)
        responds = [c["stdin"] for c in fm_calls(tmp) if c["cmd"][0] == "respond"]
        self.assertEqual(responds, ["A" * 100 + "\n\n" + "B" * 100])

    def test_trailing_newline_in_long_paragraph_does_not_make_an_empty_chunk(self):
        tmp = tempfile.mkdtemp()
        text = "\n".join(["L%d" % i + "x" * 98 for i in range(4)]) + "\n"
        p = run_afm(["ask", "S.", "--chunk", "--budget", "60"], stdin=text, tmp=tmp, env={"FAKEFM_RESPOND_MODE": "first-line"})
        self.assertEqual(p.returncode, 0, p.stderr)
        responds = [c["stdin"] for c in fm_calls(tmp) if c["cmd"][0] == "respond"]
        self.assertTrue(all(x.strip() for x in responds), responds)

    def test_crlf_input_splits_at_paragraphs(self):
        tmp = tempfile.mkdtemp()
        text = "A" * 100 + "\r\n\r\n" + "B" * 100 + "\r\n\r\n" + "C" * 100 + "\r\n"
        p = run_afm(["ask", "S.", "--chunk", "--budget", "60"], stdin=text, tmp=tmp, env={"FAKEFM_RESPOND_MODE": "first-line"})
        self.assertEqual(p.returncode, 0, p.stderr)
        responds = [c["stdin"] for c in fm_calls(tmp) if c["cmd"][0] == "respond"]
        self.assertEqual(responds, ["A" * 100 + "\n\n" + "B" * 100, "C" * 100])

    def test_non_utf8_stdin_is_accepted(self):
        tmp = tempfile.mkdtemp()
        e = dict(os.environ)
        e["PATH"] = FAKEFM + os.pathsep + e.get("PATH", "")
        e["FAKEFM_LOG"] = os.path.join(tmp, "fm.log")
        p = subprocess.run([sys.executable, AFM, "summarise"], input=b"caf\xe9 ok", capture_output=True, env=e)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_instructions_starting_with_dash_use_equals_form(self):
        tmp = tempfile.mkdtemp()
        p = run_afm(["ask", "-v: reply ok"], stdin="hello", tmp=tmp)
        self.assertEqual(p.returncode, 0, p.stderr)
        for c in fm_calls(tmp):
            if c["cmd"][0] in ("count-tokens", "respond"):
                self.assertEqual(instr_of(c["cmd"]), "-v: reply ok")
                self.assertNotIn("-i", c["cmd"])

    def test_schema_not_json_is_usage_error(self):
        tmp = tempfile.mkdtemp()
        schema = os.path.join(tmp, "bad.json")
        with open(schema, "w") as f:
            f.write("{not json")
        p = run_afm(["extract", "--schema", schema], stdin="x", tmp=tmp)
        self.assertEqual(p.returncode, 2, p.stderr)
        self.assertIn("not valid JSON", p.stderr)
        self.assertEqual(fm_calls(tmp), [])

    def test_schema_without_x_order_is_usage_error(self):
        tmp = tempfile.mkdtemp()
        schema = os.path.join(tmp, "no-order.json")
        with open(schema, "w") as f:
            json.dump({"type": "object"}, f)
        p = run_afm(["extract", "--schema", schema], stdin="x", tmp=tmp)
        self.assertEqual(p.returncode, 2, p.stderr)
        self.assertIn("x-order", p.stderr)

    def test_commit_msg_over_budget_advice_is_not_chunk(self):
        p = run_afm(["commit-msg", "--budget", "50"], stdin="x" * 1000)
        self.assertEqual(p.returncode, 6, p.stderr)
        self.assertNotIn("--chunk", p.stderr)
        self.assertIn("smaller diff", p.stderr)

    def test_single_line_over_budget_message_includes_overhead(self):
        p = run_afm(["ask", "S.", "--chunk", "--budget", "20"], stdin="y" * 400)
        self.assertEqual(p.returncode, 6, p.stderr)
        self.assertIn("line 1 is 100 tokens plus 1 for instructions and schema, budget is 20", p.stderr)

    def test_max_chunks_exactly_n_is_fine(self):
        tmp = tempfile.mkdtemp()
        text = "\n\n".join(["P" * 100] * 3)
        p = run_afm(["ask", "S.", "--chunk", "--budget", "30", "--max-chunks", "3"], stdin=text, tmp=tmp)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.count("["), 3)

    def test_planning_stops_at_max_chunks_plus_one(self):
        tmp = tempfile.mkdtemp()
        text = "\n\n".join(["P" * 100] * 50)
        p = run_afm(["ask", "S.", "--chunk", "--budget", "30", "--max-chunks", "2"], stdin=text, tmp=tmp)
        self.assertEqual(p.returncode, 6, p.stderr)
        counts = [c for c in fm_calls(tmp) if c["cmd"][0] == "count-tokens"]
        self.assertLess(len(counts), 10, "planning should stop after max+1 pieces")

    def test_pop_branch_when_estimate_underpredicts(self):
        tmp = tempfile.mkdtemp()
        # B is 20 tokens heavier than its bytes suggest: the estimate packs A+B (65 < 70) but the
        # recount says 71, so B must be popped; likewise B+C.
        text = "\n\n".join(["A" * 100, "B" * 100, "C" * 100])
        p = run_afm(["ask", "S.", "--chunk", "--budget", "70"], stdin=text, tmp=tmp,
                    env={"FAKEFM_RESPOND_MODE": "first-line", "FAKEFM_COUNT_EXTRA_IF_CONTAINS": "B:20"})
        self.assertEqual(p.returncode, 0, p.stderr)
        responds = [c["stdin"] for c in fm_calls(tmp) if c["cmd"][0] == "respond"]
        self.assertEqual(responds, ["A" * 100, "B" * 100, "C" * 100])

    def test_timeout_inside_chunk(self):
        tmp = tempfile.mkdtemp()
        text = "\n\n".join(["P" * 100] * 2)
        p = run_afm(["ask", "S.", "--chunk", "--budget", "30", "--timeout", "0.5"], stdin=text, tmp=tmp,
                    env={"FAKEFM_RESPOND_DELAY": "5"})
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn("chunk 1/2: timed out after 0.5 s", p.stderr)
        self.assertEqual(p.stdout, "")

    def test_exit_3_inside_chunk(self):
        tmp = tempfile.mkdtemp()
        text = "\n\n".join(["P" * 100] * 2)
        p = run_afm(["classify", "--labels", "a,b", "--chunk", "--budget", "115"], stdin=text, tmp=tmp,
                    env={"FAKEFM_RESPOND_STDOUT": '{"label": "zzz"}'})
        self.assertEqual(p.returncode, 3, p.stderr)
        self.assertIn("chunk 1/2: label 'zzz'", p.stderr)
        self.assertEqual(p.stdout, "")

    def test_available_returning_1008_is_exit_5(self):
        p = run_afm(["summarise"], stdin="hello", env={
            "FAKEFM_RESPOND_EXIT": "1", "FAKEFM_RESPOND_STDERR": "Error: x\n",
            "FAKEFM_AVAILABLE_EXIT": "1", "FAKEFM_AVAILABLE_STDERR": SANDBOX_MSG})
        self.assertEqual(p.returncode, 5, p.stderr)

    def test_fm_not_executable_is_exit_4(self):
        tmp = tempfile.mkdtemp()
        bindir = os.path.join(tmp, "bin")
        os.mkdir(bindir)
        with open(os.path.join(bindir, "fm"), "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(os.path.join(bindir, "fm"), 0o644)
        p = run_afm(["summarise"], stdin="hello", tmp=tmp, env={"PATH": bindir})
        self.assertEqual(p.returncode, 4, p.stderr)

    def test_empty_model_output_is_exit_1(self):
        p = run_afm(["summarise"], stdin="hello", env={"FAKEFM_RESPOND_STDOUT": "   "})
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn("no output", p.stderr)
        self.assertEqual(p.stdout, "")

    def test_ansi_stripped_from_fm_stderr(self):
        p = run_afm(["summarise"], stdin="hello", env={
            "FAKEFM_RESPOND_EXIT": "1", "FAKEFM_RESPOND_STDERR": "Error: \x1b[38;2;255;107;128mBad thing\x1b[0m\n"})
        self.assertEqual(p.returncode, 1)
        self.assertIn("Bad thing", p.stderr)
        self.assertNotIn("\x1b", p.stderr)

    def test_bad_timeout_and_max_chunks_are_usage_errors(self):
        for args in (["summarise", "--timeout", "0"], ["summarise", "--timeout", "-1"], ["summarise", "--timeout", "nan"],
                     ["summarise", "--timeout", "inf"], ["summarise", "--chunk", "--max-chunks", "0"], ["summarise", "--budget", "0"]):
            p = run_afm(args, stdin="hello")
            self.assertEqual(p.returncode, 2, (args, p.stderr))

    def test_labels_with_quotes_or_backslash_are_usage_errors(self):
        for labels in ('a,b"c', "a,b'c", "a,x\\y"):
            p = run_afm(["classify", "--labels", labels], stdin="hello")
            self.assertEqual(p.returncode, 2, (labels, p.stderr))

    def test_count_tokens_honours_timeout(self):
        p = run_afm(["summarise", "--timeout", "0.5"], stdin="hello", env={"FAKEFM_COUNT_DELAY": "5"})
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn("timed out", p.stderr)


def real_model_works():
    env = dict(os.environ)
    try:
        if subprocess.run(["fm", "available"], capture_output=True, env=env).returncode != 0:
            return False
        return subprocess.run(["fm", "respond", "--no-stream", "hi"], capture_output=True, env=env,
                              timeout=60).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


@unittest.skipUnless(real_model_works(), "on-device model not usable here")
class IntegrationTests(unittest.TestCase):
    def test_classify_real(self):
        p = subprocess.run([AFM, "classify", "--labels", "positive,negative"], input="I absolutely loved this film.",
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn(json.loads(p.stdout)["label"], ("positive", "negative"))


if __name__ == "__main__":
    unittest.main()
