"""Tests: the code in the user documents runs (plan step 14). Every ```python block of README.md and docs/user_guide.md is run in a fresh Python process
from the project folder, unless its first line says `# not run`, and prints what the text says it prints; the node author guide's build command for the example node
is the one test_package.py compiles it with."""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOCUMENTS = ("README.md", os.path.join("docs", "user_guide.md"))
FENCE = re.compile(r"^```python\r?\n(.*?)^```", re.S | re.M)

# a piece of the output that each block (found by a piece of its text) must have printed
EXPECTED = {
    'print(instance.value("y", 0))': ["0.69999"],
    "for b in engine.boundary_nodes()": ["x inlet", "y outlet", "0.69999"],
    "print(repr(engine.node_message(song.id)))": ["''", "480 0.488"],
    "ns_to_frame_fraction(251_000_000, 44100)": ["480 11069 0.1"],
    "again.to_dict() == graph.to_dict()": ["True"],
    "graph.can_connect": ["1 2 boundary_inlet", "already connected"],
}


def blocks():
    found = []
    for name in DOCUMENTS:
        with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
            text = handle.read()
        for match in FENCE.finditer(text):
            found.append((name, match.group(1).replace("\r\n", "\n")))
    return found


def test_py_every_python_example_in_the_user_documents_runs_and_prints_what_the_text_says():
    found = blocks()
    runnable = [(name, code) for name, code in found if not code.lstrip().startswith("# not run")]
    assert len(found) >= 8 and len(runnable) >= 7, (len(found), len(runnable))
    wanted = dict(EXPECTED)
    for name, code in runnable:
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, f"a block of {name} failed:\n{code}\n{result.stdout}\n{result.stderr}"
        for piece, outputs in list(wanted.items()):
            if piece in code:
                for output in outputs:
                    assert output in result.stdout, f"a block of {name} (with {piece!r}) printed\n{result.stdout}\nwithout {output!r}"
                del wanted[piece]
    assert not wanted, f"no runnable block contains {list(wanted)}"


def test_py_the_blocks_that_are_not_run_are_only_the_ones_that_open_a_window():
    skipped = [code for _name, code in blocks() if code.lstrip().startswith("# not run")]
    assert skipped and all("tk.Tk()" in code for code in skipped), skipped


def test_py_the_documents_name_files_that_exist():
    wanted = {"README.md": ("run_editor.bat", "examples/section15.py", "docs/user_guide.md", "docs/node_author_guide.md", "docs/canopy_design.md",
                            "docs/THIRD_PARTY_NOTICES.txt", "dev/package.py"),
              os.path.join("docs", "node_author_guide.md"): ("examples/example_node.c", "examples/use_example_node.py", "src/canopy_test_nodes.c",
                                                              "src/canopy_fileread.c", "tests/c/test_overrun.c", "tests/c/support.c"),
              os.path.join("docs", "user_guide.md"): ("tests/python/test_docs.py", "canopysynth/app.py")}
    for document, names in wanted.items():
        with open(os.path.join(ROOT, document), encoding="utf-8") as handle:
            text = handle.read()
        for name in names:
            assert name in text, f"{document} does not mention {name}"
            assert os.path.exists(os.path.join(ROOT, *name.split("/"))), f"{document} names {name}, which does not exist"
    guide = open(os.path.join(ROOT, "docs", "user_guide.md"), encoding="utf-8").read()
    for sibling in ("node_author_guide.md", "canopy_design.md"):
        assert sibling in guide and os.path.exists(os.path.join(ROOT, "docs", sibling))
