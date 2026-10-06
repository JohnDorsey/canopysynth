"""The mutations of the changes made after the author's try-out of step 12 (a boundary node is added under a name of its own, default0, default1, ..., and
the editor refuses an empty name and a name another boundary node has): run with
    python dev/mutation/mutate.py dev/mutation/step12b.py
Every one of them should be reported as caught; see mutate.py. (V is canopysynth/editor/canvas.py, a Python file, so the runner skips the build and the extra
C runs, and AREAS limits the tests to the three editor files the new tests are in.)"""
V = "canopysynth/editor/canvas.py"

AREAS = ["editor", "editor_controls", "editor_link"]

MUTATIONS = [
    # ---- the default name ----
    ("V300 the numbering starts at 1", V, '        number = 0\n        while f"default{number}" in used:', '        number = 1\n        while f"default{number}" in used:'),
    ("V301 the name has a capital", V, '        return f"default{number}"', '        return f"Default{number}"'),
    ("V302 the number starts at the count of boundary nodes", V, '        number = 0\n        while f"default{number}" in used:', '        number = len(used)\n        while f"default{number}" in used:'),
    ("V303 only the first number is checked", V, '        while f"default{number}" in used:', '        if f"default{number}" in used:'),
    ("V304 only the names of boundary inlets are taken", V, "        used = {info.name for info in self.graph.boundary_nodes()}", '        used = {info.name for info in self.graph.boundary_nodes() if info.kind == "inlet"}'),
    ("V305 only the names of boundary outlets are taken", V, "        used = {info.name for info in self.graph.boundary_nodes()}", '        used = {info.name for info in self.graph.boundary_nodes() if info.kind == "outlet"}'),
    ("V306 every kind of node is given a name", V, "if type_key in BOUNDARY_KINDS else {}", "if True else {}"),
    ("V307 only boundary inlets are given a name", V, "if type_key in BOUNDARY_KINDS else {}", 'if type_key == "boundary_inlet" else {}'),
    ("V308 only boundary outlets are given a name", V, "if type_key in BOUNDARY_KINDS else {}", 'if type_key == "boundary_outlet" else {}'),
    ("V309 the name is not given to the node", V, "        node = self.graph.add(type_key, x=wx, y=wy, **settings)", "        node = self.graph.add(type_key, x=wx, y=wy)"),
    # ---- the refusals ----
    ("V310 an empty name is accepted", V, '        if name == "":\n            return "a boundary node needs a name', '        if False:\n            return "a boundary node needs a name'),
    ("V311 a name of spaces counts as empty", V, '        if name == "":\n            return "a boundary node needs a name', '        if name.strip() == "":\n            return "a boundary node needs a name'),
    ("V312 a name another node has is accepted", V, "            if info.name == name and info.node_id != node.id:", "            if False:"),
    ("V313 a node may not keep its own name", V, "            if info.name == name and info.node_id != node.id:", "            if info.name == name:"),
    ("V314 only the same kind of node is compared", V, "            if info.name == name and info.node_id != node.id:", "            if info.name == name and info.node_id != node.id and info.kind == BOUNDARY_KINDS[node.type]:"),
    ("V315 only the other kind of node is compared", V, "            if info.name == name and info.node_id != node.id:", "            if info.name == name and info.node_id != node.id and info.kind != BOUNDARY_KINDS[node.type]:"),
    ("V316 names are compared without regard to case", V, "            if info.name == name and info.node_id != node.id:", "            if info.name.lower() == name.lower() and info.node_id != node.id:"),
    ("V317 names are compared without their spaces", V, "            if info.name == name and info.node_id != node.id:", "            if info.name.strip() == name.strip() and info.node_id != node.id:"),
    ("V318 the text is cut of its spaces before it is checked", V, "            reason = self._boundary_name_refusal(node, value)", "            reason = self._boundary_name_refusal(node, value.strip())"),
    ("V319 a refusal is not said", V, "            if reason is not None:\n                self.say(reason)\n                return False", "            if reason is not None:\n                return False"),
    ("V320 a refusal answers yes", V, "                self.say(reason)\n                return False\n        old = node.settings[key]", "                self.say(reason)\n                return True\n        old = node.settings[key]"),
    ("V321 the refusal is not for names of boundary nodes", V, "        if node.type in BOUNDARY_KINDS and key == BOUNDARY_NAME:\n            reason =", "        if False:\n            reason ="),
    # ---- what the message says ----
    ("V322 the sentence for no name does not say why", V, '"a boundary node needs a name: the name cannot be empty"', '"the name cannot be empty"'),
    ("V323 the sentence for a taken name does not say which kind", V, "already used by another boundary node (a boundary {info.kind}); boundary names", "already used by another boundary node; boundary names"),
    ("V324 the sentence for a taken name says the wrong kind", V, "(a boundary {info.kind});", "(a boundary {BOUNDARY_KINDS[node.type]});"),
    ("V325 the sentence for a taken name does not say the name", V, 'f"the boundary name \\"{name}\\" is already used', 'f"the boundary name is already used'),
]
