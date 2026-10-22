import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL = os.path.join(ROOT, "install.sh")
FAKEFM = os.path.join(ROOT, "tests", "fakefm")


def run_install(home, agents=("claude", "codex", "opencode"), extra_env=None):
    for a in agents:
        os.makedirs(os.path.join(home, {"claude": ".claude", "codex": ".codex", "opencode": ".config/opencode"}[a]), exist_ok=True)
    e = dict(os.environ)
    e["HOME"] = home
    e["PATH"] = FAKEFM + os.pathsep + "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"
    e["AFMUX_DIR"] = os.path.join(home, ".afmux")
    e["AFMUX_REPO"] = ROOT
    e.update(extra_env or {})
    # run a copy from outside the checkout so the "use this checkout" branch is not taken
    return subprocess.run(["bash", INSTALL], capture_output=True, text=True, env=e, cwd=home,
                          stdin=subprocess.DEVNULL, timeout=120)


@unittest.skipUnless(sys.platform == "darwin", "installer is macOS only")
class InstallTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        # the installer clones from AFMUX_REPO; a dirty checkout still clones HEAD
        subprocess.run(["git", "-C", ROOT, "rev-parse", "HEAD"], check=True, capture_output=True)

    def test_fresh_install_links_everything(self):
        p = run_install(self.home)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        afm = os.path.join(self.home, ".local", "bin", "afm")
        self.assertTrue(os.path.islink(afm))
        self.assertEqual(os.path.realpath(afm), os.path.realpath(os.path.join(self.home, ".afmux", "scripts", "afm")))
        for skills in (".claude/skills", ".agents/skills"):
            link = os.path.join(self.home, skills, "afmux")
            self.assertTrue(os.path.islink(link), link)
            self.assertTrue(os.path.isfile(os.path.join(link, "SKILL.md")))
        with open(os.path.join(self.home, ".claude", "settings.json")) as f:
            self.assertIn("afm *", json.load(f)["sandbox"]["excludedCommands"])
        with open(os.path.join(self.home, ".config", "opencode", "opencode.json")) as f:
            self.assertEqual(json.load(f)["permission"]["shell"]["afm *"], "allow")
        for rules in (".claude/CLAUDE.md", ".codex/AGENTS.md", ".config/opencode/AGENTS.md"):
            with open(os.path.join(self.home, rules)) as f:
                self.assertIn("run them with `afm run`", f.read())
        with open(os.path.join(self.home, ".zprofile")) as f:
            self.assertIn(".local/bin", f.read())
        self.assertIn("afm run", p.stdout)

    def test_second_run_is_idempotent(self):
        run_install(self.home)
        p = run_install(self.home)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        with open(os.path.join(self.home, ".claude", "settings.json")) as f:
            self.assertEqual(json.load(f)["sandbox"]["excludedCommands"].count("afm *"), 1)
        with open(os.path.join(self.home, ".claude", "CLAUDE.md")) as f:
            self.assertEqual(f.read().count("run them with `afm run`"), 1)
        with open(os.path.join(self.home, ".zprofile")) as f:
            self.assertEqual(f.read().count(".local/bin"), 1)

    def test_existing_settings_are_merged_not_replaced(self):
        os.makedirs(os.path.join(self.home, ".claude"))
        with open(os.path.join(self.home, ".claude", "settings.json"), "w") as f:
            json.dump({"model": "opus", "sandbox": {"enabled": True, "excludedCommands": ["docker *"]}}, f)
        p = run_install(self.home, agents=("claude",))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        with open(os.path.join(self.home, ".claude", "settings.json")) as f:
            cfg = json.load(f)
        self.assertEqual(cfg["model"], "opus")
        self.assertEqual(cfg["sandbox"]["excludedCommands"], ["docker *", "afm *"])
        self.assertFalse(os.path.exists(os.path.join(self.home, ".codex")))

    def test_absent_agents_are_not_configured(self):
        p = run_install(self.home, agents=())
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.home, ".claude", "settings.json")))
        self.assertFalse(os.path.exists(os.path.join(self.home, ".codex")))
        self.assertTrue(os.path.islink(os.path.join(self.home, ".claude", "skills", "afmux")))

    def test_piped_script_clones_even_when_cwd_is_a_checkout(self):
        e = dict(os.environ)
        e["HOME"] = self.home
        e["PATH"] = FAKEFM + os.pathsep + "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"
        e["AFMUX_REPO"] = ROOT
        e.pop("AFMUX_DIR", None)
        with open(INSTALL) as script:
            p = subprocess.run(["bash"], stdin=script, capture_output=True, text=True, env=e, cwd=ROOT, timeout=120)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("cloned afmux into", p.stdout)
        afm = os.path.join(self.home, ".local", "bin", "afm")
        self.assertEqual(os.path.realpath(afm), os.path.realpath(os.path.join(self.home, ".afmux", "scripts", "afm")))

    def test_run_from_a_checkout_file_uses_that_checkout(self):
        e = dict(os.environ)
        e["HOME"] = self.home
        e["PATH"] = FAKEFM + os.pathsep + "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"
        e.pop("AFMUX_DIR", None)
        p = subprocess.run(["bash", INSTALL], capture_output=True, text=True, env=e, cwd=self.home,
                           stdin=subprocess.DEVNULL, timeout=120)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("using checkout at", p.stdout)
        afm = os.path.join(self.home, ".local", "bin", "afm")
        self.assertEqual(os.path.realpath(afm), os.path.realpath(os.path.join(ROOT, "scripts", "afm")))
        self.assertFalse(os.path.exists(os.path.join(self.home, ".afmux")))

    def test_malformed_settings_json_aborts_and_is_untouched(self):
        os.makedirs(os.path.join(self.home, ".claude"))
        path = os.path.join(self.home, ".claude", "settings.json")
        with open(path, "w") as f:
            f.write('{"model": "opus", // comment\n}')
        before = open(path).read()
        p = run_install(self.home, agents=("claude",))
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("not valid JSON", p.stderr)
        self.assertEqual(open(path).read(), before)
        self.assertFalse(os.path.exists(path + ".afmux-backup"))

    def test_rewritten_settings_json_keeps_a_backup(self):
        os.makedirs(os.path.join(self.home, ".claude"))
        path = os.path.join(self.home, ".claude", "settings.json")
        original = {"model": "opus", "permissions": {"allow": ["Bash(git status *)"]}}
        with open(path, "w") as f:
            json.dump(original, f)
        p = run_install(self.home, agents=("claude",))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        with open(path + ".afmux-backup") as f:
            self.assertEqual(json.load(f), original)
        with open(path) as f:
            cfg = json.load(f)
        self.assertEqual(cfg["permissions"], original["permissions"])
        self.assertEqual(cfg["sandbox"]["excludedCommands"], ["afm *"])

    def test_model_unavailable_fails_clearly(self):
        p = run_install(self.home, extra_env={"FAKEFM_AVAILABLE_EXIT": "1"})
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("not available", p.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.home, ".local", "bin", "afm")))


if __name__ == "__main__":
    unittest.main()
