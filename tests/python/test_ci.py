# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests: the GitHub Actions workflow (.github/workflows/ci.yml) stays in step with what it is meant to check. The workflow cannot be run here, so these read it as text (the
project needs only Python's standard library: no YAML reader) and cross-check the things that must agree: the Python versions it tests against the oldest one the wheel claims
(`Requires-Python`), the README's claim, the whole-suite command, and that every action it uses is pinned to a version tag."""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "dev"))
import package                                                         # noqa: E402

WORKFLOW = os.path.join(ROOT, ".github", "workflows", "ci.yml")


def workflow_text():
    with open(WORKFLOW, encoding="utf-8") as handle:
        return handle.read().replace("\r\n", "\n")


def version_tuple(text):
    return tuple(int(part) for part in text.split("."))


def claimed_minimum():
    """The oldest Python the wheel says it supports, from its own metadata: (3, 9)."""
    found = re.search(r"^Requires-Python: >=(\d+\.\d+)$", package.metadata("1.0.0"), re.M)
    assert found, "the wheel's metadata has no `Requires-Python: >=x.y` line"
    return version_tuple(found.group(1))


def tested_versions():
    """Every Python version the workflow sets up: the fixed one of the full job and the matrix of the other job, as tuples."""
    text = workflow_text()
    versions = {version_tuple(v) for v in re.findall(r'python-version: "(\d+\.\d+)"', text)}
    matrix = re.search(r"python-version: \[([^\]]*)\]", text)
    assert matrix, "the workflow has no matrix of Python versions"
    versions |= {version_tuple(v) for v in re.findall(r'"(\d+\.\d+)"', matrix.group(1))}
    return versions


def test_py_the_workflow_tests_the_oldest_python_the_wheel_claims_and_none_older():
    versions = tested_versions()
    assert min(versions) == claimed_minimum(), (sorted(versions), claimed_minimum())
    assert len(versions) >= 3, sorted(versions)                         # the oldest, the one the author's machine has (3.11) and a newer one


def test_py_the_readme_and_the_workflow_name_the_same_oldest_python():
    with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as handle:
        readme = handle.read()
    major, minor = claimed_minimum()
    assert f"Python {major}.{minor} or newer" in readme


def test_py_the_workflow_runs_the_whole_suite_and_makes_the_packages_from_that_build():
    text = workflow_text()
    assert re.search(r"^\s+run: python run_tests\.py$", text, re.M), "no job runs the whole suite as `python run_tests.py`"
    assert re.search(r"^\s+run: python dev/package\.py --no-build$", text, re.M), "the packages are not made from the build the tests ran on"
    assert "dist/*.whl" in text and "dist/*.zip" in text and "upload-artifact" in text
    assert re.search(r"^\s+run: python run_tests\.py --no-debug --no-asan$", text, re.M), "the other Python versions do not run the C tests once and the Python tests"
    assert text.count("runs-on: windows-latest") == text.count("runs-on:"), "stage 1 is Windows only: another runner needs its own build"


def test_py_the_workflow_runs_on_push_to_main_on_pull_requests_and_by_hand():
    text = workflow_text()
    assert re.search(r"^on:\n  push:\n    branches: \[main\]\n  pull_request:\n  workflow_dispatch:\n", text, re.M)


def test_py_every_action_the_workflow_uses_is_pinned_to_a_version_tag_and_it_can_only_read_the_repository():
    text = workflow_text()
    used = re.findall(r"^\s+- uses: (\S+)$", text, re.M)
    assert used, "the workflow uses no action"
    for action in used:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@v\d+", action), action     # not @main, not a branch: a moving target would change what runs
    assert re.search(r"^permissions:\n  contents: read\n", text, re.M)
