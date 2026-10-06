"""Tests: the editor widget (plan step 10), in a real tkinter window placed far off the screen (so nothing flashes) and driven with synthetic mouse
and wheel events: what is drawn (looked at through the canvas items and their tags), moving nodes, making connections by dragging (with the refused
ones, the reasons, and the marking of ports while a wire is dragged), zoom and the three kinds of panning, the add-node menu, and the messages.
Any exception inside a Tk callback fails the test (Tk would otherwise only print it)."""
import contextlib
import subprocess
import sys
import time
import tkinter as tk

import canopysynth
import engine_dll as e
from canopysynth import Graph, NodeTypes
from canopysynth import _descriptor as d
from canopysynth.editor import Editor
from canopysynth.editor import geometry as geo
from canopysynth.editor import theme

SHIFT, ALT = 0x1, 0x20000


@contextlib.contextmanager
def window(graph, width=700, height=450):
    """An Editor of `graph` in an off-screen window, with the view reset to scale 1 and offset (50, 60); yields the editor."""
    root = tk.Tk()
    problems = []
    root.report_callback_exception = lambda *details: problems.append(details)
    root.geometry(f"{width}x{height + 24}+6000+6000")
    editor = Editor(root, graph, width=width, height=height)
    editor.pack(fill="both", expand=True)
    root.update()
    editor.view = geo.View(1.0, 50.0, 60.0)
    editor.redraw()
    editor.update()
    try:
        yield editor
        editor.update()
        assert not problems, problems
    finally:
        root.destroy()


_clock = [1000]


def send(editor, sequence, x, y, **options):
    """Generates a mouse event at screen point (x, y) of the editor's canvas. Tk gives generated events the time 0, which makes any two presses at one
    spot a double click (however long between them), so every event gets a time of its own, a second after the last, unless the test passes `time`."""
    _clock[0] += 1000
    options.setdefault("time", _clock[0])
    editor.canvas.event_generate(sequence, x=int(round(x)), y=int(round(y)), **options)
    editor.update()


def press(editor, x, y, button=1):
    send(editor, f"<ButtonPress-{button}>", x, y)


def move(editor, x, y, button=1):
    send(editor, f"<B{button}-Motion>", x, y, state={1: 0x100, 2: 0x200}[button])


def release(editor, x, y, button=1):
    send(editor, f"<ButtonRelease-{button}>", x, y)


def hover(editor, x, y):
    send(editor, "<Motion>", x, y)


def wheel(editor, x, y, delta, state=0):
    send(editor, "<MouseWheel>", x, y, delta=delta, state=state)


def at(editor, x, y):
    """The screen position of a world point."""
    return editor.view.to_screen(x, y)


def port_at(editor, node, kind, key):
    box = editor.box(node)
    port = box.port(kind, key)
    return editor.view.to_screen(port.x, port.y)


def drag(editor, start, end, steps=3, button=1):
    press(editor, *start, button=button)
    for i in range(1, steps + 1):
        move(editor, start[0] + (end[0] - start[0]) * i / steps, start[1] + (end[1] - start[1]) * i / steps, button=button)
    release(editor, *end, button=button)


def types():
    """A registry with two third-party types (one flagged realtime safe, one not) and a catalog of it and the built-in ones."""
    safe = e.PyNodeType("vendor.safe", inlets=[("a", 0.0), ("b", 0.5)], outlets=["out"], flags=d.FLAG_REALTIME_SAFE, at=lambda ctx, outlet, t: 0.0)
    safe.type.name = b"Safe"
    slow = e.PyNodeType("vendor.slow", inlets=[("in", 0.0)], outlets=["out", "side"], at=lambda ctx, outlet, t: 0.0)
    slow.type.name = b"Slow"
    rig = e.Rig(slow, safe, test_nodes=True)                # (test_nodes: the hidden test_filter type, which the menu must not list)
    return rig, NodeTypes.from_registry(rig.registry, e.lib)


@contextlib.contextmanager
def sample(width=700, height=450):
    """Yields (editor, graph, nodes): file_read -> vendor.safe -> boundary_outlet, plus vendor.slow, laid out apart, no overlaps."""
    rig, catalog = types()
    try:
        graph = Graph(types=catalog)
        nodes = {
            "file": graph.add("file_read", x=0, y=40),
            "safe": graph.add("vendor.safe", x=250, y=20),
            "out": graph.add("boundary_outlet", x=500, y=40, name="out"),
            "slow": graph.add("vendor.slow", x=250, y=200),
            "level": graph.add("boundary_inlet", x=0, y=250, name="level"),
        }
        graph.connect(nodes["file"].outlet("left"), nodes["safe"].inlet("a"))
        graph.connect(nodes["safe"].outlet("out"), nodes["out"].inlet("in"))
        with window(graph, width, height) as editor:
            yield editor, graph, nodes
    finally:
        rig.close()


def items(editor, tag):
    return editor.canvas.find_withtag(tag)


def one(editor, tag):
    found = items(editor, tag)
    assert len(found) == 1, (tag, len(found))
    return found[0]


# ---------------------------------------------------------------- what is drawn

def test_py_the_editor_draws_every_node_port_title_and_wire_in_the_look_of_the_mock_up():
    with sample() as (editor, graph, nodes):
        canvas = editor.canvas
        assert len(items(editor, "body")) == 5 and len(items(editor, "wire")) == 2
        assert len(items(editor, "port")) == sum(len(n.info.inlets) + len(n.info.outlets) for n in graph.nodes()) == 2 + 3 + 1 + 2 + 1 + 1
        for node in graph.nodes():
            for p in node.info.inlets:
                one(editor, f"port:{node.id}:inlet:{p['key']}")
            for p in node.info.outlets:
                one(editor, f"port:{node.id}:outlet:{p['key']}")
        one(editor, f"wire:{nodes['safe'].id}:a")
        one(editor, f"wire:{nodes['out'].id}:in")
        assert canvas.itemcget(one(editor, "title:" + str(nodes["file"].id)), "text") == "File read"
        assert canvas.itemcget(one(editor, "title:" + str(nodes["file"].id)), "fill") == theme.TITLE_TEXT_BUILTIN
        assert items(editor, f"bar:{nodes['file'].id}") == ()                                             # a built-in node's bar is uncoloured: no bar item...
        rule = canvas.coords(one(editor, f"rule:{nodes['file'].id}"))                                     # ...but a thin off-white line under the title, short of both edges
        box = editor.box(nodes["file"])
        sx0, sy = editor.view.to_screen(box.x + theme.TITLE_RULE_INSET, box.y + box.bar)
        sx1, _ = editor.view.to_screen(box.x + box.w - theme.TITLE_RULE_INSET, box.y + box.bar)
        assert [round(v, 6) for v in rule] == [round(sx0, 6), round(sy, 6), round(sx1, 6), round(sy, 6)] and theme.TITLE_RULE_INSET > 0
        assert canvas.itemcget(one(editor, f"rule:{nodes['file'].id}"), "fill") == theme.TITLE_RULE and items(editor, f"rule:{nodes['safe'].id}") == ()
        assert canvas.itemcget(one(editor, f"title:{nodes['safe'].id}"), "text") == "Safe"
        assert canvas.itemcget(one(editor, f"title:{nodes['safe'].id}"), "fill") == theme.TITLE_BAR_TEXT
        assert canvas.itemcget(one(editor, f"bar:{nodes['safe'].id}"), "fill") == theme.TITLE_BAR_REALTIME_SAFE
        assert canvas.itemcget(one(editor, f"bar:{nodes['slow'].id}"), "fill") == theme.TITLE_BAR_NOT_REALTIME_SAFE
        assert theme.TITLE_BAR_REALTIME_SAFE != theme.TITLE_BAR_NOT_REALTIME_SAFE
        for key in ("file", "safe"):                                                                          # every title starts a little in from the node's left, in the middle of the bar
            box = editor.box(nodes[key])
            sx, sy = editor.view.to_screen(box.x + theme.TITLE_TEXT_X, box.y + box.bar / 2)
            title = canvas.coords(one(editor, f"title:{nodes[key].id}"))
            assert abs(title[0] - sx) < 0.01 and abs(title[1] - sy) < 0.01 and canvas.itemcget(one(editor, f"title:{nodes[key].id}"), "anchor") == "w"
        assert canvas.itemcget(one(editor, f"body:{nodes['file'].id}"), "fill") == theme.NODE_FILL
        assert canvas.cget("background") == theme.BACKGROUND
        everything = canvas.find_all()                                                                        # wires are behind every node
        assert max(everything.index(i) for i in items(editor, "wire")) < min(everything.index(i) for i in items(editor, "body"))


def test_py_items_sit_where_the_layout_and_the_view_put_them():
    with sample(width=1100) as (editor, graph, nodes):                 # (wide enough to hold the whole graph at this zoom: nothing is left out)
        editor.view = geo.View(1.5, 30.0, 70.0)
        editor.redraw()
        for node in graph.nodes():
            box = editor.box(node)
            for port in box.ports():
                x0, y0, x1, y1 = editor.canvas.bbox(one(editor, f"port:{node.id}:{port.kind}:{port.key}"))
                sx, sy = editor.view.to_screen(port.x, port.y)
                assert abs((x0 + x1) / 2 - sx) <= 1.5 and abs((y0 + y1) / 2 - sy) <= 1.5, (node.id, port.key)
                assert 2 * theme.PORT_RADIUS * 1.5 <= (x1 - x0) <= 2 * theme.PORT_RADIUS * 1.5 + 8                  # the diamond scales with the zoom (plus its outline)
            bx0, by0, bx1, by1 = editor.canvas.bbox(one(editor, f"body:{node.id}"))
            sx0, sy0 = editor.view.to_screen(box.x, box.y)
            assert abs(bx0 - sx0) <= 3 and abs(by0 - sy0) <= 3 and abs((bx1 - bx0) - box.w * 1.5) <= 8 and abs((by1 - by0) - box.h * 1.5) <= 8
        wire = one(editor, f"wire:{nodes['safe'].id}:a")                                                       # a wire runs from its outlet to its inlet
        coords = editor.canvas.coords(wire)
        sx, sy = port_at(editor, nodes["file"], "outlet", "left")
        ex, ey = port_at(editor, nodes["safe"], "inlet", "a")
        assert abs(coords[0] - sx) < 0.01 and abs(coords[1] - sy) < 0.01 and abs(coords[-2] - ex) < 0.01 and abs(coords[-1] - ey) < 0.01


def test_py_the_selected_node_is_outlined_and_text_is_left_out_when_it_would_be_too_small_to_read():
    with sample() as (editor, graph, nodes):
        editor.select(nodes["safe"].id)
        editor.redraw()
        assert editor.canvas.itemcget(one(editor, f"body:{nodes['safe'].id}"), "outline") == theme.NODE_OUTLINE_SELECTED
        assert editor.canvas.itemcget(one(editor, f"body:{nodes['file'].id}"), "outline") == theme.NODE_OUTLINE
        editor.view = geo.View(0.25, 0, 0)                                                                     # 16 px * 0.25 = 4 px: below MIN_TEXT_PX
        editor.redraw()
        assert items(editor, "title") == () and len(items(editor, "body")) == 5
        editor.view = geo.View(0.4, 0, 0)                                                                      # 6.4 px: drawn
        editor.redraw()
        assert len(items(editor, "title")) == 5


def test_py_the_graph_may_change_behind_the_editors_back_and_it_follows_without_error():
    with sample() as (editor, graph, nodes):
        editor.select(nodes["safe"].id)
        graph.remove(nodes["safe"])
        new = graph.add("file_read", x=300, y=300)
        editor.redraw()
        assert editor.selected is None and len(items(editor, "body")) == 5 and items(editor, f"body:{new.id}") != ()
        assert items(editor, f"body:{nodes['safe'].id}") == () and len(items(editor, "wire")) == 0
        assert sorted(box.node_id for box in editor.layout()) == sorted(n.id for n in graph.nodes())


def test_py_the_first_layout_fits_the_whole_graph_in_the_window_and_fit_and_home_do_it_again():
    rig, catalog = types()
    try:
        graph = Graph(types=catalog)
        graph.add("file_read", x=-300, y=-100)
        graph.add("boundary_outlet", x=900, y=500, name="x")
        root = tk.Tk()
        root.geometry("700x500+6000+6000")
        editor = Editor(root, graph, width=700, height=450)
        editor.pack(fill="both", expand=True)
        root.update()
        try:
            for box in editor.layout():
                x0, y0, x1, y1 = box.bbox()
                for wx, wy in ((x0, y0), (x1, y1)):
                    sx, sy = editor.view.to_screen(wx, wy)
                    assert 0 <= sx <= editor.canvas.winfo_width() and 0 <= sy <= editor.canvas.winfo_height(), (wx, wy, sx, sy)
            assert editor.view.scale < 1.0
            editor.view = geo.View(3.0, 1000, 1000)
            editor.canvas.focus_force()
            root.update()
            send(editor, "<Home>", 5, 5)
            assert editor.view.scale < 1.0
            editor.view = geo.View(3.0, 1000, 1000)
            editor.fit()
            assert editor.view.scale < 1.0
            x0, y0, x1, y1 = geo.bounding_box(editor.layout())                                                  # and the graph is centred in the canvas
            cx, cy = editor.view.to_screen((x0 + x1) / 2, (y0 + y1) / 2)
            assert abs(cx - editor.canvas.winfo_width() / 2) < 1 and abs(cy - editor.canvas.winfo_height() / 2) < 1
            editor.set_graph(Graph(types=catalog))
            assert editor.view.scale == 1.0 and editor.layout() == []                                          # nothing to fit: the default view
        finally:
            root.destroy()
    finally:
        rig.close()


def test_py_nodes_and_wires_entirely_off_the_screen_are_not_drawn_but_still_exist_for_everything_else():
    with sample() as (editor, graph, nodes):
        far = graph.add("file_read", x=5000, y=40)
        farther = graph.add("boundary_outlet", x=5400, y=40, name="far_out")
        graph.connect(far.outlet("left"), farther.inlet("in"))                                                 # both ends off the screen
        graph.connect(nodes["safe"].outlet("out"), graph.add("boundary_outlet", x=6000, y=300, name="away").inlet("in"))   # one end on it
        editor.redraw()
        assert items(editor, f"body:{far.id}") == () and items(editor, f"body:{farther.id}") == () and len(items(editor, "body")) == 5
        assert items(editor, f"wire:{farther.id}:in") == ()                                                    # a wire whose ends and curve are all off-screen
        assert len(items(editor, "wire")) == 3                                                                 # the two before and the one that reaches in
        assert items(editor, f"port:{far.id}:outlet:left") == ()
        assert len(editor.layout()) == 8                                                                       # (layout and hit testing do not depend on drawing)
        editor.view = geo.View(1.0, -4900.0, 60.0)                                                              # pan to them: now they are drawn, the others not
        editor.redraw()
        assert items(editor, f"body:{far.id}") != () and items(editor, f"body:{farther.id}") != () and items(editor, f"wire:{farther.id}:in") != ()
        assert items(editor, f"body:{nodes['file'].id}") == ()
        wx, wy = editor.view.to_world(*at(editor, far.x + 30, far.y + 30))
        assert (wx, wy) == (far.x + 30, far.y + 30)
        press(editor, *at(editor, far.x + 30, far.y + 30))                                                      # and a node on the screen can be picked as usual
        release(editor, *at(editor, far.x + 30, far.y + 30))
        assert editor.selected == far.id


# ---------------------------------------------------------------- zoom and panning

def test_py_the_wheel_zooms_around_the_pointer_shift_scrolls_sideways_alt_scrolls_up_and_down_and_the_middle_button_pans():
    with sample() as (editor, graph, nodes):
        view = editor.view
        world = view.to_world(300, 200)
        wheel(editor, 300, 200, 120)
        assert abs(view.scale - 1.1) < 1e-9
        assert all(abs(a - b) < 1e-6 for a, b in zip(view.to_screen(*world), (300, 200)))                     # the point under the pointer stayed put
        wheel(editor, 300, 200, -120)
        wheel(editor, 300, 200, -120)
        assert abs(view.scale - 1.0 / 1.1) < 1e-9
        for _ in range(60):
            wheel(editor, 100, 100, 120)
        assert view.scale == theme.ZOOM_MAX
        for _ in range(120):
            wheel(editor, 100, 100, -120)
        assert view.scale == theme.ZOOM_MIN
        editor.view.scale, editor.view.ox, editor.view.oy = 1.0, 50.0, 60.0
        wheel(editor, 300, 200, 120, state=SHIFT)                                                              # wheel up with Shift: the picture moves right
        assert (view.ox, view.oy, view.scale) == (50.0 + theme.SCROLL_STEP, 60.0, 1.0)
        wheel(editor, 300, 200, -240, state=SHIFT)
        assert view.ox == 50.0 - theme.SCROLL_STEP
        wheel(editor, 300, 200, 120, state=ALT)                                                                # with Alt: it moves down
        assert (view.ox, view.oy) == (50.0 - theme.SCROLL_STEP, 60.0 + theme.SCROLL_STEP)
        wheel(editor, 300, 200, -120, state=ALT)
        assert view.oy == 60.0
        ox, oy = view.ox, view.oy
        drag(editor, (200, 200), (260, 170), button=2)                                                         # a middle drag moves it with the pointer
        assert (view.ox, view.oy, view.scale) == (ox + 60, oy - 30, 1.0)
        assert [n.x for n in graph.nodes()] == [0, 250, 500, 250, 0]                                           # panning moves no node


def test_py_zooming_changes_how_far_a_drag_moves_a_node_in_the_world_and_a_wheel_notch_is_a_tenth():
    with sample() as (editor, graph, nodes):
        wheel(editor, 0, 0, 120 * 7)                                                                           # seven notches in: 1.1 ** 7 = 1.9487
        scale = editor.view.scale
        assert abs(scale - 1.1 ** 7) < 1e-9
        box = editor.box(nodes["file"])
        start = editor.view.to_screen(box.x + 20, box.y + 20)
        before = (nodes["file"].x, nodes["file"].y)
        drag(editor, start, (start[0] + 100, start[1] + 40), steps=4)
        assert abs(nodes["file"].x - (before[0] + 100 / scale)) < 1.0 and abs(nodes["file"].y - (before[1] + 40 / scale)) < 1.0


# ---------------------------------------------------------------- moving nodes

def test_py_dragging_a_node_moves_it_selects_it_brings_it_to_the_front_and_reports_moves():
    with sample() as (editor, graph, nodes):
        kinds = []
        editor.add_listener(kinds.append)
        box = editor.box(nodes["file"])
        start = at(editor, box.x + 30, box.y + 30)
        press(editor, *start)
        assert editor.selected == nodes["file"].id and editor.layout()[-1].node_id == nodes["file"].id
        move(editor, start[0] + 12, start[1] - 7)
        assert (nodes["file"].x, nodes["file"].y) == (12, 33)
        move(editor, start[0] + 50, start[1] + 10)
        release(editor, start[0] + 50, start[1] + 10)
        assert (nodes["file"].x, nodes["file"].y) == (50, 50)
        assert kinds == ["moved", "moved"] and editor._drag is None
        box = editor.box(nodes["file"])
        assert (box.x, box.y) == (50, 50)                                                                      # the layout follows the model
        press(editor, 650, 420)                                                                                # a click on the background deselects
        release(editor, 650, 420)
        assert editor.selected is None
        title = editor.box(nodes["slow"])                                                                      # a third-party node moves by its title bar too
        grab = at(editor, title.x + 20, title.y + 10)
        drag(editor, grab, (grab[0] - 30, grab[1] + 30))
        assert (nodes["slow"].x, nodes["slow"].y) == (220, 230)
        built_in = editor.box(nodes["out"])                                                                    # and a built-in node by its (uncoloured) title bar
        grab = at(editor, built_in.x + 5, built_in.y + 5)
        drag(editor, grab, (grab[0] + 10, grab[1] + 10))
        assert (nodes["out"].x, nodes["out"].y) == (510, 50)
        assert [n.type for n in graph.nodes()].count("file_read") == 1 and graph.connections()[0].outlet.node is nodes["file"]


# ---------------------------------------------------------------- connecting

def test_py_dragging_from_an_outlet_to_an_inlet_connects_them_and_tells_the_listeners():
    with sample() as (editor, graph, nodes):
        kinds, virtual = [], []
        editor.add_listener(kinds.append)
        editor.bind("<<GraphChanged>>", lambda event: virtual.append(1))
        start = port_at(editor, nodes["safe"], "outlet", "out")                    # fan-out: this outlet already feeds the boundary outlet
        end = port_at(editor, nodes["slow"], "inlet", "in")
        drag(editor, start, end)
        connection = graph.connection_into(nodes["slow"].inlet("in"))
        assert connection is not None and connection.outlet == nodes["safe"].outlet("out")
        assert kinds == ["connected"] and virtual == [1] and editor.message == ""
        assert len(items(editor, "wire")) == 3 and items(editor, "pending") == ()
        one(editor, f"wire:{nodes['slow'].id}:in")
        start = port_at(editor, nodes["level"], "outlet", "out")                    # and from a built-in boundary node into a third-party inlet
        drag(editor, start, port_at(editor, nodes["safe"], "inlet", "b"))
        assert graph.connection_into(nodes["safe"].inlet("b")).outlet.node is nodes["level"]


def test_py_dragging_from_a_free_inlet_to_an_outlet_connects_them_too():
    with sample() as (editor, graph, nodes):
        drag(editor, port_at(editor, nodes["slow"], "inlet", "in"), port_at(editor, nodes["file"], "outlet", "right"))
        connection = graph.connection_into(nodes["slow"].inlet("in"))
        assert connection is not None and connection.outlet == nodes["file"].outlet("right")


def test_py_while_a_wire_is_dragged_the_pending_wire_follows_the_pointer_and_ports_show_where_it_may_go():
    with sample() as (editor, graph, nodes):
        start = port_at(editor, nodes["file"], "outlet", "right")
        press(editor, *start)
        move(editor, 400, 380)
        pending = one(editor, "pending")
        coords = editor.canvas.coords(pending)
        assert abs(coords[0] - start[0]) < 0.01 and abs(coords[-2] - 400) < 0.5 and abs(coords[-1] - 380) < 0.5       # it ends at the pointer
        fills = lambda node, kind, key: editor.canvas.itemcget(one(editor, f"port:{node.id}:{kind}:{key}"), "fill")
        lines = lambda node, kind, key: editor.canvas.itemcget(one(editor, f"port:{node.id}:{kind}:{key}"), "outline")
        assert lines(nodes["slow"], "inlet", "in") == theme.PORT_OUTLINE_TARGET and fills(nodes["slow"], "inlet", "in") == theme.PORT_FILL
        assert lines(nodes["safe"], "inlet", "b") == theme.PORT_OUTLINE_TARGET
        assert fills(nodes["safe"], "inlet", "a") == theme.PORT_FILL_REFUSED                                    # already has a connection
        assert fills(nodes["safe"], "outlet", "out") == theme.PORT_FILL_REFUSED                                 # an outlet is no target for an outlet's wire
        assert fills(nodes["file"], "outlet", "left") == theme.PORT_FILL_REFUSED
        assert lines(nodes["file"], "outlet", "right") == theme.PORT_OUTLINE_TARGET                             # the anchor stays lit
        target = port_at(editor, nodes["slow"], "inlet", "in")
        move(editor, target[0] + 3, target[1] + 2)                                                              # near a port it may go to: it snaps to it
        coords = editor.canvas.coords(one(editor, "pending"))
        assert abs(coords[-2] - target[0]) < 0.5 and abs(coords[-1] - target[1]) < 0.5
        refused = port_at(editor, nodes["safe"], "inlet", "a")
        move(editor, refused[0] + 3, refused[1] + 2)                                                            # near a port it may not go to: it does not snap
        coords = editor.canvas.coords(one(editor, "pending"))
        assert abs(coords[-2] - (refused[0] + 3)) < 0.5 and abs(coords[-1] - (refused[1] + 2)) < 0.5
        move(editor, 400, 380)
        release(editor, 400, 380)                                                                               # dropped on nothing: nothing happens
        assert items(editor, "pending") == () and len(graph.connections()) == 2 and editor.message == ""
        assert lines(nodes["slow"], "inlet", "in") == theme.PORT_OUTLINE and fills(nodes["safe"], "inlet", "a") == theme.PORT_FILL


def test_py_connections_the_graph_would_refuse_are_refused_with_the_reason_and_change_nothing():
    with sample() as (editor, graph, nodes):
        kinds = []
        editor.add_listener(kinds.append)

        def refused(start, end, *fragments):
            before = graph.to_dict()
            editor.say("", seconds=0)
            drag(editor, start, end)
            assert graph.to_dict() == before and kinds == [], (start, end)
            for fragment in fragments:
                assert fragment in editor.message, (fragment, editor.message)

        taken = port_at(editor, nodes["safe"], "inlet", "a")
        refused(port_at(editor, nodes["file"], "outlet", "right"), taken, "already connected")                      # an inlet takes one connection
        refused(port_at(editor, nodes["file"], "outlet", "right"), port_at(editor, nodes["out"], "inlet", "in"), "already connected")
        refused(port_at(editor, nodes["safe"], "outlet", "out"), port_at(editor, nodes["file"], "outlet", "left"))      # outlet onto outlet: nothing
        assert editor.message == ""
        refused(port_at(editor, nodes["safe"], "inlet", "b"), port_at(editor, nodes["slow"], "inlet", "in"))            # inlet onto inlet: nothing
        assert editor.message == ""
        refused(port_at(editor, nodes["safe"], "outlet", "out"), port_at(editor, nodes["safe"], "inlet", "b"), "loop", "loop_protection")   # a node into itself
        graph.connect(nodes["safe"].outlet("out"), nodes["slow"].inlet("in"))
        editor.redraw()
        kinds.clear()
        refused(port_at(editor, nodes["slow"], "outlet", "out"), port_at(editor, nodes["safe"], "inlet", "b"), "loop")  # safe -> slow -> safe
        refused(port_at(editor, nodes["safe"], "inlet", "b"), port_at(editor, nodes["slow"], "outlet", "side"), "loop")  # the same, dragged from the inlet end
        drag(editor, port_at(editor, nodes["slow"], "outlet", "out"), port_at(editor, nodes["out"], "inlet", "in"))     # (taken: refused)
        assert kinds == []
        drag(editor, port_at(editor, nodes["level"], "outlet", "out"), port_at(editor, nodes["safe"], "inlet", "b"))    # and a harmless one still works
        assert kinds == ["connected"] and graph.connection_into(nodes["safe"].inlet("b")) is not None


def test_py_a_loop_is_allowed_when_the_graph_has_loop_protection_off_and_a_node_into_itself_is_a_loop():
    with sample() as (editor, graph, nodes):
        graph.loop_protection = False
        editor.redraw()
        drag(editor, port_at(editor, nodes["slow"], "outlet", "out"), port_at(editor, nodes["slow"], "inlet", "in"))
        assert graph.connection_into(nodes["slow"].inlet("in")).outlet == nodes["slow"].outlet("out") and graph.has_loop()
        assert editor.message == ""


def test_py_pressing_an_inlet_that_already_has_a_connection_starts_no_wire_and_says_why_and_escape_cancels_a_wire():
    with sample() as (editor, graph, nodes):
        taken = port_at(editor, nodes["safe"], "inlet", "a")
        press(editor, *taken)
        assert editor._drag is None and "already has a connection" in editor.message
        move(editor, taken[0] - 40, taken[1])
        release(editor, taken[0] - 40, taken[1])
        assert len(graph.connections()) == 2 and nodes["safe"].x == 250                                        # and it did not move the node
        start = port_at(editor, nodes["file"], "outlet", "right")
        press(editor, *start)
        move(editor, 300, 300)
        assert items(editor, "pending") != ()
        editor.canvas.focus_force()                                                                             # (key events go to the focus window)
        editor.update()
        send(editor, "<Escape>", 300, 300)
        assert items(editor, "pending") == () and editor._drag is None
        release(editor, *port_at(editor, nodes["slow"], "inlet", "in"))                                         # releasing over an inlet now does nothing
        assert graph.connection_into(nodes["slow"].inlet("in")) is None


def test_py_the_port_under_the_pointer_shows_its_label_next_to_it():
    with sample() as (editor, graph, nodes):
        assert items(editor, "tooltip") == ()
        spot = port_at(editor, nodes["slow"], "outlet", "side")
        hover(editor, *spot)
        texts = [editor.canvas.itemcget(i, "text") for i in items(editor, "tooltip") if editor.canvas.type(i) == "text"]
        assert texts == ["side"]                                                                               # the label is the key here (the test type's)
        assert editor.canvas.itemcget(one(editor, f"port:{nodes['slow'].id}:outlet:side"), "outline") == theme.PORT_OUTLINE_HOVER
        hover(editor, 650, 420)
        assert items(editor, "tooltip") == ()
        hover(editor, *port_at(editor, nodes["file"], "outlet", "left"))
        assert [editor.canvas.itemcget(i, "text") for i in items(editor, "tooltip") if editor.canvas.type(i) == "text"] == ["Left"]
        send(editor, "<Leave>", 5, 5)
        assert items(editor, "tooltip") == ()


# ---------------------------------------------------------------- the add-node menu

def test_py_the_add_menu_lists_built_in_types_first_then_third_party_ones_and_hides_the_test_type():
    with sample() as (editor, graph, nodes):
        menu = editor.build_add_menu(10, 20)
        labels = []
        for index in range(menu.index("end") + 1):
            labels.append("---" if menu.type(index) == "separator" else menu.entrycget(index, "label"))
        assert labels == ["Boundary inlet", "Boundary outlet", "File read", "Realtime preview", "---", "Safe", "Slow  (not realtime safe)",
                          "---", "Loop protection"], labels
        assert "test_filter" not in "".join(labels) and "Test filter" not in "".join(labels)


def test_py_choosing_an_entry_of_the_add_menu_adds_a_node_at_the_clicked_world_point_and_selects_it():
    with sample() as (editor, graph, nodes):
        kinds = []
        editor.add_listener(kinds.append)
        editor.view = geo.View(2.0, 100.0, 50.0)
        popups = []
        editor._popup = lambda menu, x_root, y_root: popups.append((menu, x_root, y_root))
        send(editor, "<ButtonPress-3>", 450, 380)                                                              # empty: world (175, 165)
        assert len(popups) == 1
        menu = popups[0][0]
        labels = [menu.entrycget(i, "label") for i in range(menu.index("end") + 1) if menu.type(i) == "command"]
        index = labels.index("Realtime preview")
        menu.invoke(index)
        node = graph.nodes()[-1]
        assert node.type == "realtime_preview" and (node.x, node.y) == (175.0, 165.0) and len(graph.nodes()) == 6
        assert editor.selected == node.id and kinds == ["added"] and editor.layout()[-1].node_id == node.id
        editor.redraw()
        one(editor, f"body:{node.id}")
        menu.invoke(labels.index("Safe") + 1)                                                                   # (the separator is entry 4)
        assert graph.nodes()[-1].type == "vendor.safe"
        box = editor.box(nodes["file"])                                                                         # a right click on a node opens the node's menu
        send(editor, "<ButtonPress-3>", *at(editor, box.x + 20, box.y + 20))
        assert len(popups) == 2 and popups[1][0].entrycget(0, "label") == "Delete" and editor.selected == nodes["file"].id


def test_py_a_boundary_node_added_from_the_menu_is_named_default0_default1_and_so_on_with_the_first_name_no_boundary_node_has():
    with sample() as (editor, graph, nodes):                                                                    # boundary nodes "out" (an outlet) and "level" (an inlet)
        popups = []
        editor._popup = lambda menu, x_root, y_root: popups.append(menu)
        send(editor, "<ButtonPress-3>", 600, 400)
        menu = popups[0]
        labels = [menu.entrycget(i, "label") for i in range(menu.index("end") + 1) if menu.type(i) == "command"]
        inlet, outlet, preview = (labels.index(label) for label in ("Boundary inlet", "Boundary outlet", "Realtime preview"))     # (built-in types: the entries before the separator)
        menu.invoke(inlet)
        menu.invoke(outlet)
        menu.invoke(inlet)
        first, second, third = graph.nodes()[-3:]
        assert [(n.type, n.settings["name"]) for n in (first, second, third)] == [
            ("boundary_inlet", "default0"), ("boundary_outlet", "default1"), ("boundary_inlet", "default2")]       # one numbering for both kinds
        graph.validate()                                                                                          # (raises if a name is empty or used twice)
        menu.invoke(preview)
        assert "name" not in graph.nodes()[-1].settings                                                           # no other type is touched
        editor.edit_setting(first, "name", "mine")                                                                # a number that is free again comes first, not the one after the last
        editor.remove_node(second)
        menu.invoke(outlet)
        menu.invoke(inlet)
        menu.invoke(outlet)
        assert [n.settings["name"] for n in graph.nodes()[-3:]] == ["default0", "default1", "default3"]          # (default2 is taken)
        graph.validate()
        editor.edit_setting(first, "name", "default4")                                                            # a name the user typed that looks like one is taken like any other
        assert editor.add_node("boundary_inlet", 0, 0).settings["name"] == "default5"
        graph.validate()
        assert graph.add("boundary_inlet").settings["name"] == ""                                                 # the model adds nodes as it is told: a host picks its own names


def test_py_the_message_line_shows_a_sentence_for_a_while_and_then_clears():
    with sample() as (editor, graph, nodes):
        editor.say("hello", seconds=0.1)
        assert editor.message == "hello"
        time.sleep(0.25)
        editor.update()
        assert editor.message == ""
        editor.say("first", seconds=0.1)
        editor.say("second", seconds=0.5)                                                                       # a newer sentence replaces the older one...
        time.sleep(0.25)
        editor.update()
        assert editor.message == "second"                                                                       # ...and the older one's timer does not clear it
        time.sleep(0.4)
        editor.update()
        assert editor.message == ""


def test_py_canopysynth_editor_is_found_lazily_and_importing_the_package_does_not_load_tkinter():
    code = "import sys, canopysynth; print('tkinter' in sys.modules); E = canopysynth.Editor; print('tkinter' in sys.modules, E.__name__)"
    import os
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=root, env=dict(os.environ, PYTHONPATH=root))
    assert result.stdout.split() == ["False", "True", "Editor"], (result.stdout, result.stderr)
    assert canopysynth.Editor is Editor
    try:
        canopysynth.NoSuchThing
    except AttributeError:
        pass
    else:
        raise AssertionError("an unknown name must raise AttributeError")


def test_py_the_real_window_check_script_runs_clean_off_screen_without_pauses():
    import os
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    result = subprocess.run([sys.executable, os.path.join(root, "dev", "editor_check.py"), "--offscreen", "--fast"], capture_output=True, text=True,
                            cwd=root, timeout=120)
    assert result.returncode == 0 and "editor check passed (45 checks)" in result.stdout, (result.stdout[-600:], result.stderr[-600:])


def test_py_destroying_the_editor_cancels_its_timers_so_nothing_runs_after_the_window_is_gone():
    code = (
        "import sys, tkinter as tk\n"
        "sys.path.insert(0, r'%s')\n"
        "import canopysynth\n"
        "from canopysynth.editor import Editor\n"
        "root = tk.Tk(); root.geometry('300x200+6000+6000')\n"
        "root.tk.eval('proc bgerror {message} {lappend ::background_errors $message}')\n"       # Tk would swallow a failed timer: record it instead
        "editor = Editor(root, canopysynth.Graph(), width=300, height=150); editor.pack(); root.update()\n"
        "import time\n"
        "editor.say('a message that would clear in a moment', seconds=0.2)\n"
        "editor._invalidate()\n"
        "editor.destroy()\n"
        "end = time.time() + 0.6\n"
        "while time.time() < end:\n"
        "    root.update(); time.sleep(0.02)\n"
        "try:\n"
        "    print('background errors:', root.tk.eval('set ::background_errors'))\n"
        "except tk.TclError:\n"
        "    print('no background errors')\n"
        "root.destroy()\n"
        "print('done')\n"
    )
    import os
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    result = subprocess.run([sys.executable, "-c", code % base], capture_output=True, text=True, timeout=60)
    assert result.stdout.split("\n")[:2] == ["no background errors", "done"] and result.stderr == "", (result.stdout, result.stderr)


def test_py_line_widths_and_font_sizes_follow_the_zoom_and_text_appears_exactly_at_the_size_threshold():
    from tkinter import font as tkfont
    with sample(width=1500, height=900) as (editor, graph, nodes):
        for scale, wire_width, title_size in ((1.0, 4, 16), (2.0, 8, 32), (0.5, 2, 8)):
            editor.view = geo.View(scale, 20.0, 40.0)
            editor.redraw()
            assert int(float(editor.canvas.itemcget(one(editor, f"wire:{nodes['safe'].id}:a"), "width"))) == wire_width
            font = tkfont.Font(root=editor, name=editor.canvas.itemcget(one(editor, f"title:{nodes['safe'].id}"), "font"), exists=True)
            assert font.cget("size") == -title_size and font.cget("weight") == "bold", (scale, font.actual())
        editor.view = geo.View(0.3125, 20.0, 40.0)                                                              # 16 px * 0.3125 = exactly MIN_TEXT_PX
        editor.redraw()
        assert len(items(editor, "title")) == 5
        editor.view = geo.View(0.3124, 20.0, 40.0)
        editor.redraw()
        assert items(editor, "title") == ()


def test_py_what_is_just_off_the_screen_is_drawn_up_to_the_margin_and_not_beyond_it():
    with sample() as (editor, graph, nodes):
        canvas_width = editor.canvas.winfo_width()
        near = graph.add("file_read", x=0, y=0)
        far = graph.add("file_read", x=0, y=0)
        for node, offset in ((near, theme.CULL_MARGIN - 2), (far, theme.CULL_MARGIN + 2)):                          # put the node's left edge just right of the canvas
            box = editor.box(node)
            node.x += (canvas_width + offset - editor.view.to_screen(box.bbox()[0], 0)[0]) / editor.view.scale
        editor.redraw()
        assert items(editor, f"body:{near.id}") != () and items(editor, f"body:{far.id}") == ()
        canvas_height = editor.canvas.winfo_height()
        for node, above, offset in ((near, True, theme.CULL_MARGIN - 2), (far, True, theme.CULL_MARGIN + 2),
                                    (graph.add("file_read", x=0, y=0), False, theme.CULL_MARGIN - 2), (graph.add("file_read", x=0, y=0), False, theme.CULL_MARGIN + 2)):
            x0, y0, x1, y1 = editor.box(node).bbox()
            if above:                                                                                           # just above the canvas
                node.x = -editor.view.ox / editor.view.scale + 100
                node.y += (-offset - editor.view.to_screen(0, y1)[1]) / editor.view.scale
            else:                                                                                               # just left of it
                node.y = -editor.view.oy / editor.view.scale + 100
                node.x += (-offset - editor.view.to_screen(x1, 0)[0]) / editor.view.scale
        editor.redraw()
        ids = [n.id for n in graph.nodes()][-4:]
        assert [items(editor, f"body:{i}") != () for i in ids] == [True, False, True, False]


def test_py_a_wire_dragged_from_an_inlet_runs_from_the_pointer_to_the_inlet_and_marks_the_outlets():
    with sample() as (editor, graph, nodes):
        start = port_at(editor, nodes["slow"], "inlet", "in")
        press(editor, *start)
        move(editor, 150, 380)
        coords = editor.canvas.coords(one(editor, "pending"))
        assert abs(coords[0] - 150) < 0.5 and abs(coords[1] - 380) < 0.5 and abs(coords[-2] - start[0]) < 0.01 and abs(coords[-1] - start[1]) < 0.01
        fill = lambda node, kind, key: editor.canvas.itemcget(one(editor, f"port:{node.id}:{kind}:{key}"), "fill")
        line = lambda node, kind, key: editor.canvas.itemcget(one(editor, f"port:{node.id}:{kind}:{key}"), "outline")
        assert line(nodes["file"], "outlet", "left") == theme.PORT_OUTLINE_TARGET and fill(nodes["file"], "outlet", "left") == theme.PORT_FILL
        assert line(nodes["safe"], "outlet", "out") == theme.PORT_OUTLINE_TARGET and line(nodes["level"], "outlet", "out") == theme.PORT_OUTLINE_TARGET
        assert fill(nodes["safe"], "inlet", "b") == theme.PORT_FILL_REFUSED and fill(nodes["slow"], "outlet", "out") == theme.PORT_FILL_REFUSED
        assert line(nodes["slow"], "inlet", "in") == theme.PORT_OUTLINE_TARGET                                     # the anchor stays lit
        snap = port_at(editor, nodes["level"], "outlet", "out")
        move(editor, snap[0] + 2, snap[1] + 2)
        coords = editor.canvas.coords(one(editor, "pending"))
        assert abs(coords[0] - snap[0]) < 0.5 and abs(coords[1] - snap[1]) < 0.5                                   # it snapped to that outlet
        release(editor, snap[0] + 2, snap[1] + 2)
        assert graph.connection_into(nodes["slow"].inlet("in")).outlet.node is nodes["level"]


def test_py_ports_are_hit_at_other_zoom_levels_with_a_radius_of_screen_pixels():
    with sample(width=1400, height=900) as (editor, graph, nodes):
        editor.view = geo.View(2.0, 30.0, 40.0)
        editor.redraw()
        start, end = port_at(editor, nodes["safe"], "outlet", "out"), port_at(editor, nodes["slow"], "inlet", "in")
        drag(editor, (start[0] + 9, start[1] - 9), (end[0] - 9, end[1] + 9))                                        # 9 px off a port: inside its 14 px radius
        assert graph.connection_into(nodes["slow"].inlet("in")) is not None
        editor.view = geo.View(0.5, 30.0, 40.0)
        editor.redraw()
        start, end = port_at(editor, nodes["level"], "outlet", "out"), port_at(editor, nodes["safe"], "inlet", "b")
        drag(editor, (start[0] + 12, start[1]), (end[0] + 12, end[1]))                                              # (12 px into the node: left of an inlet is its knob)
        assert graph.connection_into(nodes["safe"].inlet("b")) is not None
        far_start = port_at(editor, nodes["file"], "outlet", "right")
        press(editor, far_start[0] + 20, far_start[1])                                                              # 20 px away: not on the port
        assert editor._drag is None or editor._drag[0] != "wire"
        release(editor, far_start[0] + 20, far_start[1])


def test_py_tooltips_sit_beside_their_ports_pressing_takes_the_focus_and_the_popup_goes_where_the_pointer_is():
    with sample() as (editor, graph, nodes):
        inlet = port_at(editor, nodes["safe"], "inlet", "b")
        hover(editor, *inlet)
        text = [i for i in items(editor, "tooltip") if editor.canvas.type(i) == "text"][0]
        assert editor.canvas.bbox(text)[2] < inlet[0]                                                              # an inlet's label is on its left
        outlet = port_at(editor, nodes["safe"], "outlet", "out")
        hover(editor, *outlet)
        text = [i for i in items(editor, "tooltip") if editor.canvas.type(i) == "text"][0]
        assert editor.canvas.bbox(text)[0] > outlet[0]                                                             # an outlet's on its right
        box = editor.box(nodes["file"])
        spot = at(editor, box.x + 30, box.y + 30)
        press(editor, *spot)
        release(editor, *spot)
        assert str(editor.focus_lastfor()) == str(editor.canvas)
        taken = port_at(editor, nodes["out"], "inlet", "in")
        press(editor, *taken)
        release(editor, *taken)
        assert editor.selected == nodes["out"].id                                                                  # (a press on a taken inlet still selects its node)
        popups = []
        editor._popup = lambda menu, x_root, y_root: popups.append((x_root, y_root))
        send(editor, "<ButtonPress-3>", 450, 380)
        assert popups == [(editor.canvas.winfo_rootx() + 450, editor.canvas.winfo_rooty() + 380)]


def test_py_unknown_nodes_and_replaced_graphs_are_handled_by_the_editor():
    with sample() as (editor, graph, nodes):
        from canopysynth import GraphError
        try:
            editor.box(99999)
        except GraphError:
            pass
        else:
            raise AssertionError("box of a node that is not there must raise GraphError")
        assert editor.box(nodes["file"].id).node_id == nodes["file"].id
        editor.select(nodes["file"].id)                                                                        # ID 1: the new graph has a node 1 too
        other = Graph(types=graph.types)
        other.add("file_read", x=10, y=10)
        editor.set_graph(other)
        assert editor.selected is None and editor.graph is other and [b.node_id for b in editor.layout()] == [1]
