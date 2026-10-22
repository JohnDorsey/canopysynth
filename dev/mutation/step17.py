# SPDX-License-Identifier: GPL-3.0-or-later
"""The mutations for the CI workflow of stage 1 (build 22): the workflow file, and the two other places that must agree with it (the wheel's `Requires-Python`, the README).
The files are text, so the runner skips the build and the C tests, and AREAS limits the tests to test_ci.py. Run with
    python dev/mutation/mutate.py dev/mutation/step17.py
Every one should be reported as caught."""
W = ".github/workflows/ci.yml"

AREAS = ["ci"]

MUTATIONS = [
    ("C01 the oldest Python is no longer tested", W, '["3.9", "3.10", "3.12", "3.13"]', '["3.10", "3.12", "3.13"]'),
    ("C02 the wheel claims an older Python than the workflow tests", "dev/package.py", '"Requires-Python: >=3.9"', '"Requires-Python: >=3.8"'),
    ("C03 the README claims an older Python than the wheel", "README.md", "Python 3.9 or newer", "Python 3.8 or newer"),
    ("C04 the full job no longer runs the whole suite", W, "        run: python run_tests.py\n      - name: Which test programs", "        run: python run_tests.py --no-c\n      - name: Which test programs"),
    ("C05 the packages are built again instead of from the tested build", W, "run: python dev/package.py --no-build", "run: python dev/package.py"),
    ("C06 an action follows a branch instead of a tag", W, "      - uses: actions/checkout@v4\n      - uses: actions/setup-python@v5\n        with:\n          python-version: \"3.11\"",
     "      - uses: actions/checkout@main\n      - uses: actions/setup-python@v5\n        with:\n          python-version: \"3.11\""),
    ("C07 pull requests are no longer tested", W, "  pull_request:\n", ""),
    ("C08 one job moves to another operating system without its own build", W, "    runs-on: windows-latest\n    timeout-minutes: 45\n    strategy:", "    runs-on: macos-latest\n    timeout-minutes: 45\n    strategy:"),
    ("C09 the workflow may write to the repository", W, "  contents: read\n", "  contents: write\n"),
    ("C10 the zip is no longer kept", W, "            dist/*.zip\n", ""),
    ("C11 the other Python versions run no tests", W, "run_tests.py --no-debug --no-asan", "run_tests.py --no-debug --no-asan --no-c --no-build -k nothing_matches"),
    ("C12 the workflow cannot be started by hand", W, "  workflow_dispatch:\n", ""),
]
