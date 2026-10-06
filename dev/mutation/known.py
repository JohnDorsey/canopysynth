"""Four mutations whose verdicts are known beforehand: a check of the mutation runner itself, in either of its modes (the fast one and --thorough), that it
still reports a mutation that no test notices as SURVIVED (every other spec expects "caught" for everything, so none of them could show that). Run with
    python dev/mutation/mutate.py dev/mutation/known.py [--thorough]
and expect exactly this (the exit code is 1, because of the two survivors):
    E1 SURVIVED   a comment reworded: nothing a test can see
    E2 SURVIVED   `+ 0` added to a size: the same value
    K1 caught     by a test that runs early in the fast order (the rectangle selection)
    K2 caught     by a test that only the slow link tests make: the engine is no longer collected after a node is removed
(G is canopysynth/editor/geometry.py, V canvas.py, L link.py: Python files, so the runner skips the build and the extra C runs; AREAS limits the tests.)"""
G = "canopysynth/editor/geometry.py"
V = "canopysynth/editor/canvas.py"
L = "canopysynth/editor/link.py"

AREAS = ["editor", "editor_controls", "editor_geometry", "editor_selection", "editor_link"]

MUTATIONS = [
    ("E1 a comment is reworded", V, "# the hidden test-only node type is not in the add-node list (design section 11)", "# the hidden test-only node type is left out of the add-node list (design section 11)"),
    ("E2 a size has a zero added", V, "        return max(1, round(units * self.view.scale))", "        return max(1, round(units * self.view.scale) + 0)"),
    ("K1 a rectangle is not put in order", G, "    rect = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))", "    rect = (x0, y0, x1, y1)"),
    ("K2 the engine is not collected after a removal", L, "        if edit.kind == \"removed\":\n            self.engine.collect()", "        if False:\n            self.engine.collect()"),
]
