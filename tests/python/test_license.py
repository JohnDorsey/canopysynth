# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests: the licence of CANOPY (GPL-3.0-or-later) is in the project the way the packages and the README promise: the LICENSE file is the FSF's text of version 3, every source
file of ours names the licence in one of its first lines, the vendored third-party files are left byte for byte as they were downloaded (they have licences of their own), and
the old name of the host program (renamed to PrismaticFractals) is gone from the project's text."""
import hashlib
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKIP_FOLDERS = {".git", "build", "dist", "__pycache__", "third_party"}
SOURCE_EXTENSIONS = {".c", ".h", ".py", ".ps1", ".bat"}
TEXT_EXTENSIONS = SOURCE_EXTENSIONS | {".md", ".txt", ".json"}
SPDX_LINE = re.compile(r"^(/\* |# |@?rem )SPDX-License-Identifier: GPL-3\.0-or-later( \*/)?$")

# The SHA-256 of the FSF's gpl-3.0.txt (35,149 bytes, LF line endings), as downloaded from https://www.gnu.org/licenses/gpl-3.0.txt on 2026-10-20.
GPL3_SHA256 = "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986"


def project_files(extensions):
    """Every file of the project with one of the extensions, outside the folders that are generated or vendored: [(path relative to the project, absolute path)]."""
    found = []
    for folder, dirs, names in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_FOLDERS]
        for name in names:
            if os.path.splitext(name)[1] in extensions:
                path = os.path.join(folder, name)
                found.append((os.path.relpath(path, ROOT).replace(os.sep, "/"), path))
    return sorted(found)


def read(path):
    with open(path, "rb") as handle:
        return handle.read()


def test_py_the_license_file_is_the_text_of_the_gpl_version_3_exactly():
    text = read(os.path.join(ROOT, "LICENSE")).replace(b"\r\n", b"\n")
    assert len(text) == 35149, len(text)
    assert hashlib.sha256(text).hexdigest() == GPL3_SHA256
    assert text.startswith(b"                    GNU GENERAL PUBLIC LICENSE\n                       Version 3, 29 June 2007\n")


def test_py_every_source_file_of_ours_says_in_one_of_its_first_lines_that_it_is_gpl_3_or_later():
    files = project_files(SOURCE_EXTENSIONS)
    assert len(files) > 100, len(files)                                    # (the walk found the project: a wrong ROOT would find none and pass)
    missing = []
    for name, path in files:
        first = read(path).decode("utf-8").splitlines()[:2]
        if not any(SPDX_LINE.match(line) for line in first):
            missing.append(name)
    assert not missing, missing


def test_py_the_spdx_line_never_comes_before_a_shebang_and_never_prints_when_a_batch_file_runs():
    for name, path in project_files({".bat"}):
        lines = read(path).decode("utf-8").splitlines()
        assert lines[0].startswith("@rem SPDX"), (name, lines[0])          # a plain `rem` above `@echo off` would be printed to the console
    for name, path in project_files({".py"}):
        lines = read(path).decode("utf-8").splitlines()
        for number, line in enumerate(lines[:2]):
            if line.startswith("#!"):
                assert number == 0, name


def test_py_the_third_party_files_have_no_line_of_ours_added_to_them():
    folder = os.path.join(ROOT, "third_party")
    for name in os.listdir(folder):
        if name.endswith((".h", ".c")):
            assert b"GPL-3.0-or-later" not in read(os.path.join(folder, name)), name


def test_py_the_readme_and_the_package_metadata_name_the_same_license_as_the_source_files():
    import sys
    sys.path.insert(0, os.path.join(ROOT, "dev"))
    import package
    assert package.LICENSE_ID == "GPL-3.0-or-later"
    readme = read(os.path.join(ROOT, "README.md")).decode("utf-8")
    assert "`GPL-3.0-or-later`" in readme and "## Licence" in readme
    assert "No licence has been chosen" not in readme
    assert f"License: {package.LICENSE_ID}" in package.metadata("1.0.0")


def test_py_the_old_name_of_the_host_program_is_not_used_anywhere_in_the_projects_text():
    old = "light" + "_bounces"                                            # (spelled in two pieces so that this file does not contain it)
    found = [name for name, path in project_files(TEXT_EXTENSIONS) if old in read(path).decode("utf-8", "replace").lower()]
    assert not found, found
