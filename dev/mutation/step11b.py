"""The mutations of the changes made after the author's try-out of step 11 (an inlet that has a connection shows no knob; rectangular selection and
moving the selection together): run with
    python dev/mutation/mutate.py dev/mutation/step11b.py
Every one of them should be reported as caught; see mutate.py. (G is canopysynth/editor/geometry.py, V canopysynth/editor/canvas.py, T theme.py. They
are all Python files, so the runner skips the build and the extra C runs, and AREAS limits the tests to the editor's four files.)"""
G = "canopysynth/editor/geometry.py"
V = "canopysynth/editor/canvas.py"
T = "canopysynth/editor/theme.py"

AREAS = ["editor", "editor_controls", "editor_geometry", "editor_selection", "editor_link"]

MUTATIONS = [
    # ---- hidden knobs ----
    ("G110 an inlet that has a connection keeps its knob", G, "        if node.graph.connection_into(node.inlet(port.key)) is not None:", "        if False:"),
    ("G111 only an inlet that has a connection has a knob", G, "        if node.graph.connection_into(node.inlet(port.key)) is not None:", "        if node.graph.connection_into(node.inlet(port.key)) is None:"),
    ("G112 an inlet that has a connection ends the knobs", G, "is not None:      # an inlet that has a connection shows no knob (design section 6)\n            continue", "is not None:      # an inlet that has a connection shows no knob (design section 6)\n            break"),
    # ---- the rectangle ----
    ("G113 a rectangle is not put in order", G, "    rect = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))", "    rect = (x0, y0, x1, y1)"),
    ("G114 a rectangle's top is not put in order", G, "min(y0, y1), max(x0, x1)", "y0, max(x0, x1)"),
    ("G115 a rectangle's right is not put in order", G, "max(x0, x1), max(y0, y1))", "x1, max(y0, y1))"),
    ("G116 a node's body is as tall as nothing", G, "overlaps((box.x, box.y, box.x + box.w, box.y + box.h), rect)", "overlaps((box.x, box.y, box.x + box.w, box.y), rect)"),
    ("G117 a node's body is as wide as nothing", G, "overlaps((box.x, box.y, box.x + box.w, box.y + box.h), rect)", "overlaps((box.x, box.y, box.x, box.y + box.h), rect)"),
    ("G118 a node counts with its ports and knobs", G, "overlaps((box.x, box.y, box.x + box.w, box.y + box.h), rect)", "overlaps(box.bbox(), rect)"),
    ("G119 only nodes wholly inside the rectangle count", G, "overlaps((box.x, box.y, box.x + box.w, box.y + box.h), rect)", "(rect[0] <= box.x and rect[1] <= box.y and box.x + box.w <= rect[2] and box.y + box.h <= rect[3])"),
    ("G120 the nodes come back in reverse", G, "    return [box.node_id for box in boxes if", "    return [box.node_id for box in reversed(boxes) if"),
    ("T20 the rectangle is drawn with a solid line", T, "MARQUEE_DASH = (5, 3)", "MARQUEE_DASH = ()"),
    # ---- the selection ----
    ("V190 selected is any one of several", V, "if len(self._selection) == 1 else None", "if len(self._selection) >= 1 else None"),
    ("V191 the selection can be changed from outside", V, "        return frozenset(self._selection)", "        return self._selection"),
    ("V192 select adds to the selection", V, "self._selection = set() if node_id is None else {node_id}", "self._selection = set() if node_id is None else self._selection | {node_id}"),
    ("V193 select_nodes takes IDs the graph does not have", V, "for node_id in node_ids if node_id in present}", "for node_id in node_ids}"),
    ("V194 select_nodes is not drawn", V, "        self._selection = {node_id for node_id in node_ids if node_id in present}\n        self._invalidate()", "        self._selection = {node_id for node_id in node_ids if node_id in present}"),
    ("V195 only one selected node is drawn as selected", V, "node_id, selected = box.node_id, box.node_id in self._selection", "node_id, selected = box.node_id, box.node_id == self.selected"),
    ("V196 a press on the background does not start a rectangle", V, "            self._drag = (\"marquee\", event.x, event.y)\n            return", "            return"),
    ("V197 the rectangle does not select", V, "        elif self._drag[0] == \"marquee\":", "        elif False:"),
    ("V198 the rectangle is measured from where the pointer is", V, "x0, y0 = self.view.to_world(start_x, start_y)", "x0, y0 = self.view.to_world(event.x, event.y)"),
    ("V199 the rectangle is in screen units", V, "geo.nodes_in_rect(self.layout(), (x0, y0, x1, y1))", "geo.nodes_in_rect(self.layout(), (start_x, start_y, event.x, event.y))"),
    ("V200 the rectangle is not drawn", V, "        if self._drag is not None and self._drag[0] == \"marquee\":\n            canvas.create_rectangle(", "        if False:\n            canvas.create_rectangle("),
    ("V201 the rectangle starts at the corner of the window", V, "canvas.create_rectangle(self._drag[1], self._drag[2], *self._pointer,", "canvas.create_rectangle(0, 0, *self._pointer,"),
    ("V202 the rectangle is not dashed", V, "dash=theme.MARQUEE_DASH,", "dash=(),"),
    ("V203 the rectangle is drawn in the node outline", V, "canvas.create_rectangle(self._drag[1], self._drag[2], *self._pointer, outline=theme.NODE_OUTLINE_SELECTED,", "canvas.create_rectangle(self._drag[1], self._drag[2], *self._pointer, outline=theme.NODE_OUTLINE,"),
    # ---- moving the selection ----
    ("V204 a press on a node always selects it alone", V, "        if box.node_id not in self._selection:           # a node of the selection", "        if True:           # a node of the selection"),
    ("V205 a press on a node never selects it", V, "        if box.node_id not in self._selection:           # a node of the selection", "        if False:           # a node of the selection"),
    ("V206 a drag moves only the node pressed", V, "            for node_id in self._selection:                                  # the selection moves together", "            for node_id in (clicked,):                                  # the selection moves together"),
    ("V207 a drag is not marked as a drag", V, "            self._drag = (\"node\", event.x, event.y, clicked, True)", "            self._drag = (\"node\", event.x, event.y, clicked, False)"),
    ("V208 a press starts as a drag already", V, "        self._drag = (\"node\", event.x, event.y, box.node_id, False)", "        self._drag = (\"node\", event.x, event.y, box.node_id, True)"),
    ("V209 a click on a group member keeps the group", V, "            if not drag[4] and len(self._selection) > 1:", "            if False:"),
    ("V210 a drag of a group narrows it afterwards", V, "            if not drag[4] and len(self._selection) > 1:", "            if len(self._selection) > 1:"),
    ("V211 a click on a member of a pair keeps the pair", V, "            if not drag[4] and len(self._selection) > 1:", "            if not drag[4] and len(self._selection) > 2:"),
    ("V212 a click on a group member selects no one", V, "                self.select(drag[3])", "                self.select(None)"),
    ("V213 a click on a group member does not bring it to the front", V, "                self.select(drag[3])", "                self._selection = {drag[3]}"),
    ("V214 a right click on the background clears the selection", V, "                self._menu_world = self.view.to_world(event.x, event.y)", "                self.select(None)\n                self._menu_world = self.view.to_world(event.x, event.y)"),
    ("V215 a right click on an outlet may offer to disconnect", V, "inlet_key = hit[2].key if hit[0] == \"port\" and hit[2].kind == \"inlet\" else None", "inlet_key = hit[2].key if hit[0] == \"port\" else None"),
    ("V216 a node in a group is dragged by the pointer's last place", V, "            _, last_x, last_y, clicked, _moved = self._drag", "            _, last_x, last_y, clicked, _moved = self._drag\n            last_x, last_y = last_x + 1, last_y"),
]
