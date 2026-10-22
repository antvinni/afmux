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


if __name__ == "__main__":
    unittest.main()
