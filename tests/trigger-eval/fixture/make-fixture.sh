#!/bin/bash
# Build a throwaway repo with long test output, a big log, a build log and a staged change.
set -euo pipefail
dest="${1:?usage: make-fixture.sh DIR}"
rm -rf "$dest"; mkdir -p "$dest/tests"; cd "$dest"
git init -q
cat > util.py <<'PY'
def parse_date(s):
    y, m, d = s.split("-")
    return int(y), int(m), int(d) + 1  # bug: off by one
PY
cat > tests/__init__.py <<'PY'
PY
cat > tests/test_util.py <<'PY'
import unittest
from util import parse_date


class ParseDateTests(unittest.TestCase):
    pass


def _make(day):
    def test(self):
        s = "2026-01-%02d" % day
        for i in range(30):
            print("debug line", i, "for", s)
        self.assertEqual(parse_date(s), (2026, 1, day))
    return test


for _day in range(1, 21):
    setattr(ParseDateTests, "test_parse_date_%02d" % _day, _make(_day))
PY
python3 - <<'PY'
import random
random.seed(1)
with open("app.log", "w") as f:
    for i in range(2000):
        level = random.choice(["INFO"] * 8 + ["WARN"] * 1 + ["ERROR"] * 1)
        f.write("2026-10-22 10:%02d:%02d %s worker-%d request %d %s\n" % (i // 60 % 60, i % 60, level, i % 4, i, "ok" if level == "INFO" else "failed: timeout"))
with open("build.log", "w") as f:
    f.write("clang version 17.0.0\n")
    for i in range(1500):
        if i % 100 == 7:
            f.write("src/file%d.c:%d:5: warning: unused variable 'x'\n" % (i, i))
        elif i % 500 == 3:
            f.write("src/file%d.c:%d:5: error: expected ';'\n" % (i, i))
        else:
            f.write("[%d/1500] compiling src/file%d.c\n" % (i, i))
PY
git add -A && git commit -qm "fixture"
printf '\ndef format_date(y, m, d):\n    return "%%04d-%%02d-%%02d" %% (y, m, d)\n' >> util.py
git add util.py
echo "fixture ready at $dest (15 warnings, 3 errors in build.log; all 20 tests fail)"
