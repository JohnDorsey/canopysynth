"""Tests: what the editor shows and does with a node's knobs, widgets and menus (plan step 11), in a real tkinter window placed far off the screen and
driven with synthetic events, like test_editor.py (whose helpers it uses). The node types here are written by hand as descriptors (no DLL rig needed)
next to the built-in ones, so that a node with every kind of setting and widget, and one with an internal sampling rate, can be tried."""
import contextlib
import random

from canopysynth import Graph, GraphError, NodeTypes
from canopysynth.editor import geometry as geo
from canopysynth.editor import theme
from test_editor import _clock, at, drag, hover, items, move, one, port_at, press, release, send, window


def descriptor(key, name, inlets=(), outlets=("out",), settings=(), widgets=(), realtime_safe=True, internal_rate=False):
    return {"key": key, "name": name, "type_version": 1, "realtime_safe": realtime_safe, "has_internal_rate": internal_rate,
            "inlets": [{"key": k, "label": k.upper(), "default_knob": v} for k, v in inlets], "outlets": [{"key": k, "label": k} for k in outlets],
            "settings": list(settings), "widgets": list(widgets), "scratch_buffers": 0, "handlers": {}}


def setting(key, kind, default, choices=()):
    return {"key": key, "kind": kind, "default": default, "choices": list(choices)}


def widget(kind, label, setting=None, action=None, choices=()):
    return {"kind": kind, "label": label, "setting": setting, "action": action, "choices": list(choices)}


PANEL = descriptor("vendor.panel", "Panel", inlets=[("a", 0.0), ("b", 0.5)], outlets=["out"],
                   settings=[setting("count", "int", 3), setting("gain", "float", 0.5), setting("tag", "string", "hi"), setting("file", "path", ""),
                             setting("mode", "choice", 0, ["sine", "square", "saw"])],
                   widgets=[widget("label", "Controls"), widget("text", "Count", "count"), widget("text", "Gain", "gain"), widget("text", "Tag", "tag"),
                            widget("text", "File", "file"), widget("choice", "Mode", "mode"), widget("button", "Reset", action="reset"),
                            widget("screen", "Picture")])                                              # (the last kind is one the editor does not know)
FILTER = descriptor("vendor.filter", "Filter", inlets=[("in", 0.0)], outlets=["out"], settings=[setting("internal_sampling_rate", "int", 48000)],
                    realtime_safe=False, internal_rate=True)


def make_catalog():
    base = Graph().types
    return NodeTypes([base.get(key).data for key in base.keys()] + [PANEL, FILTER])


CATALOG = make_catalog()


@contextlib.contextmanager
def controls():
    """Yields (editor, graph, nodes): a panel with every kind of widget, a filter with an internal rate, boundary nodes and a file node; src -> panel.a
    and filter -> out are connected. The view is at scale 1, offset (50, 60)."""
    graph = Graph(types=CATALOG)
    nodes = {
        "panel": graph.add("vendor.panel", x=200, y=10),
        "filter": graph.add("vendor.filter", x=450, y=20),
        "out": graph.add("boundary_outlet", x=450, y=150, name="out"),
        "src": graph.add("boundary_inlet", x=10, y=340, name="src"),
        "file": graph.add("file_read", x=450, y=300),
    }
    graph.connect(nodes["src"].outlet("out"), nodes["panel"].inlet("a"))
    graph.connect(nodes["filter"].outlet("out"), nodes["out"].inlet("in"))
    with window(graph, 1000, 700) as editor:
        yield editor, graph, nodes


def listen(editor):
    """Records what the editor tells its listeners and how often <<GraphChanged>> is generated: returns (kinds, virtual)."""
    kinds, virtual = [], []
    editor.add_listener(kinds.append)
    editor.bind("<<GraphChanged>>", lambda event: virtual.append(1))
    return kinds, virtual


def widgets_of(editor, node):
    return {w.label: w for w in editor.box(node).widgets}


def knob_point(editor, node, key):
    knob = editor.box(node).knob(key)
    return at(editor, knob.cx, knob.cy)


def field_point(editor, node, label):
    w = widgets_of(editor, node)[label]
    return at(editor, w.field_x + 10, w.y + w.h / 2)


def double_click(editor, x, y):
    """Two presses of the left button 100 ms apart at one spot (Tk decides on double clicks by the events' own times)."""
    _clock[0] += 10000
    base = _clock[0]
    send(editor, "<ButtonPress-1>", x, y, time=base)
    send(editor, "<ButtonRelease-1>", x, y, time=base + 10)
    send(editor, "<ButtonPress-1>", x, y, time=base + 100)
    send(editor, "<ButtonRelease-1>", x, y, time=base + 110)


def click(editor, x, y):
    press(editor, x, y)
    release(editor, x, y)


def right_click(editor, x, y):
    send(editor, "<ButtonPress-3>", x, y)


def catch_menus(editor):
    """Replaces the pop-up (which would wait for a click) by a list of the menus that would have been shown."""
    shown = []
    editor._popup = lambda menu, x_root, y_root: shown.append(menu)
    return shown


def labels(menu):
    return [menu.entrycget(i, "label") for i in range(menu.index("end") + 1) if menu.type(i) != "separator"]


def type_into_box(editor, text, key="<Return>"):
    """Types `text` into the text box the editor has open (replacing what it holds) and presses `key` in it."""
    assert editor._entry is not None, "no text box is open"
    entry = editor._entry[0]
    entry.delete(0, "end")
    entry.insert(0, text)
    entry.focus_force()
    entry.update()
    entry.event_generate(key)
    editor.update()


def tooltip_texts(editor):
    return [editor.canvas.itemcget(i, "text") for i in items(editor, "tooltip") if editor.canvas.type(i) == "text"]


# ---------------------------------------------------------------- knobs

def test_py_every_unconnected_inlet_shows_its_knob_in_a_pill_with_the_tick_at_its_position_and_a_connected_one_shows_none():
    with controls() as (editor, graph, nodes):
        canvas, panel = editor.canvas, nodes["panel"]
        assert len(items(editor, "knob")) == 2 == len(items(editor, "dial")) == len(items(editor, "tick"))          # panel b and the filter's inlet: panel a and the boundary outlet's have wires
        one(editor, f"knob:{panel.id}:b"), one(editor, f"dial:{panel.id}:b"), one(editor, f"tick:{panel.id}:b"), one(editor, f"knob:{nodes['filter'].id}:in")
        for kind in ("knob", "dial", "tick"):
            assert items(editor, f"{kind}:{panel.id}:a") == () and items(editor, f"{kind}:{nodes['out'].id}:in") == ()      # connected: nothing is drawn for it
        assert items(editor, f"knob:{nodes['file'].id}:left") == () and items(editor, f"knob:{nodes['src'].id}:out") == ()       # outlets have none
        box = editor.box(panel)
        knob = box.knob("b")
        tx0, ty0, tx1, ty1 = geo.knob_tick(knob.cx, knob.cy, knob.r, 0.5)
        expected = list(editor.view.to_screen(tx0, ty0)) + list(editor.view.to_screen(tx1, ty1))
        assert all(abs(a - b) < 0.01 for a, b in zip(canvas.coords(one(editor, f"tick:{panel.id}:b")), expected))
        x0, y0, x1, y1 = canvas.bbox(one(editor, f"knob:{panel.id}:b"))                                              # the pill is left of the node, level with its port
        sx, sy = port_at(editor, panel, "inlet", "b")
        assert x1 < sx - 5 and x0 < x1 - 40 and abs((y0 + y1) / 2 - sy) <= 1.5
        fill = lambda tag: canvas.itemcget(one(editor, tag), "fill")
        assert fill(f"knob:{panel.id}:b") == theme.KNOB_PILL_FILL and fill(f"dial:{panel.id}:b") == theme.KNOB_DIAL_FILL and fill(f"tick:{panel.id}:b") == theme.KNOB_TICK
        assert canvas.itemcget(one(editor, f"dial:{panel.id}:b"), "outline") == theme.KNOB_DIAL_OUTLINE
        before = canvas.coords(one(editor, f"tick:{panel.id}:b"))
        panel.set_knob("b", -1.0)                                                                                    # the tick follows the model
        editor.redraw()
        after = canvas.coords(one(editor, f"tick:{panel.id}:b"))
        assert after != before and after[2] < after[0]                                                               # -1 points to the left of the centre
        panel.set_knob("a", 0.75)                                                                                    # a wire hides the knob, taking away the wire brings it back as it was
        assert editor.disconnect(panel.inlet("a"))
        editor.redraw()
        shown_tick = canvas.coords(one(editor, f"tick:{panel.id}:a"))
        knob_a = editor.box(panel).knob("a")
        tx0, ty0, tx1, ty1 = geo.knob_tick(knob_a.cx, knob_a.cy, knob_a.r, 0.75)
        assert all(abs(a - b) < 0.01 for a, b in zip(shown_tick, list(editor.view.to_screen(tx0, ty0)) + list(editor.view.to_screen(tx1, ty1))))
        assert editor.connect(nodes["src"].outlet("out"), panel.inlet("a"))
        editor.redraw()
        assert items(editor, f"knob:{panel.id}:a") == () and editor.box(panel).knob("a") is None and panel.knobs["a"] == 0.75


def test_py_every_knob_turns_translucent_while_a_wire_is_dragged_and_opaque_again_after():
    with controls() as (editor, graph, nodes):
        canvas, panel = editor.canvas, nodes["panel"]
        blend = lambda colour: theme.blend(colour, theme.BACKGROUND, theme.KNOB_TRANSLUCENT)
        press(editor, *port_at(editor, nodes["file"], "outlet", "left"))
        move(editor, 400, 500)
        fill = lambda tag: canvas.itemcget(one(editor, tag), "fill")
        assert fill(f"knob:{panel.id}:b") == blend(theme.KNOB_PILL_FILL) and fill(f"dial:{panel.id}:b") == blend(theme.KNOB_DIAL_FILL)
        assert fill(f"tick:{panel.id}:b") == blend(theme.KNOB_TICK) and canvas.itemcget(one(editor, f"dial:{panel.id}:b"), "outline") == blend(theme.KNOB_DIAL_OUTLINE)
        assert items(editor, f"knob:{panel.id}:a") == ()                                                             # (still none for a connected inlet)
        assert fill(f"knob:{nodes['filter'].id}:in") == blend(theme.KNOB_PILL_FILL)
        assert blend(theme.KNOB_PILL_FILL) != theme.KNOB_PILL_FILL and blend(theme.KNOB_TICK) != theme.KNOB_TICK
        release(editor, 400, 500)
        assert fill(f"knob:{panel.id}:b") == theme.KNOB_PILL_FILL and fill(f"tick:{panel.id}:b") == theme.KNOB_TICK
        press(editor, *port_at(editor, nodes["file"], "outlet", "left"))                                              # and Escape ends it as well
        assert fill(f"knob:{panel.id}:b") == theme.blend(theme.KNOB_PILL_FILL, theme.BACKGROUND, theme.KNOB_TRANSLUCENT)
        editor.canvas.focus_force()                                                                                  # (key events go to the focus window)
        editor.update()
        send(editor, "<Escape>", 5, 5)
        assert editor._drag is None and fill(f"knob:{panel.id}:b") == theme.KNOB_PILL_FILL


def test_py_dragging_a_free_knob_turns_it_200_pixels_for_its_whole_range_whatever_the_zoom_and_tells_the_listeners_quietly():
    with controls() as (editor, graph, nodes):
        kinds, virtual = listen(editor)
        panel = nodes["panel"]
        x, y = knob_point(editor, panel, "b")                                                                        # starts at 0.5
        press(editor, x, y)
        assert editor._drag[0] == "knob" and editor.selected == panel.id and (panel.x, panel.y) == (200, 10)
        move(editor, x + 3, y - 50)                                                                                  # (sideways movement does nothing)
        tick = editor.canvas.coords(one(editor, f"tick:{panel.id}:b"))
        assert panel.knobs["b"] == 1.0 and tick[2] > tick[0] and tick[3] > tick[1]                                   # +1: the tick points down and to the right
        move(editor, x, y + 50)                                                                                     # measured from where it was pressed, not the last step
        assert panel.knobs["b"] == 0.0 and tooltip_texts(editor) == ["B: 0"]                                         # its raw value is shown while it is dragged
        move(editor, x, y - 400)
        assert panel.knobs["b"] == 1.0                                                                               # limited to 1...
        move(editor, x, y + 400)
        assert panel.knobs["b"] == -1.0 and tooltip_texts(editor) == ["B: -1"]                                       # ...and -1
        move(editor, x, y + 450)
        release(editor, x, y + 450)
        assert panel.knobs["b"] == -1.0 and editor._drag is None and tooltip_texts(editor) == [] and (panel.x, panel.y) == (200, 10)
        assert kinds == ["knob"] * 4 and virtual == []                                                               # (no event for a value that did not change; none generated for knobs)
        editor.view = geo.View(2.0, 50.0, 60.0)
        editor.redraw()
        x, y = knob_point(editor, panel, "b")
        drag(editor, (x, y), (x, y - 50), steps=2)                                                                   # 50 screen pixels at zoom 2: still +0.5
        assert panel.knobs["b"] == -0.5


def test_py_a_quick_second_press_is_an_ordinary_press_everywhere_except_on_a_free_knob():
    with controls() as (editor, graph, nodes):
        panel = nodes["panel"]
        box = editor.box(panel)
        x, y = at(editor, box.x + 100, box.y + 8)                                                                      # the title bar
        double_click(editor, x, y)
        assert editor.selected == panel.id and editor._entry is None and editor._drag is None
        double_click(editor, 700, 650)                                                                                 # the background
        assert editor.selected is None
        double_click(editor, *field_point(editor, panel, "Count"))                                                     # a text box: the box opens as for one press
        assert editor._entry is not None and editor._entry[0].get() == "3"
        type_into_box(editor, "ignored", key="<Escape>")
        _clock[0] += 10000                                                                                             # the second press of a double click must itself select and grab:
        base = _clock[0]                                                                                               # between the two presses the selection is taken away
        send(editor, "<ButtonPress-1>", x, y, time=base)
        send(editor, "<ButtonRelease-1>", x, y, time=base + 10)
        editor.select(None)
        send(editor, "<ButtonPress-1>", x, y, time=base + 100)
        assert editor.selected == panel.id and editor._drag is not None and editor._drag[0] == "node"
        send(editor, "<ButtonRelease-1>", x, y, time=base + 110)
        move_to = at(editor, box.x + 100, box.y + 8)
        press(editor, *move_to)                                                                                        # (a press and a drag after a double click still move the node)
        move(editor, move_to[0] + 20, move_to[1] + 10)
        release(editor, move_to[0] + 20, move_to[1] + 10)
        assert (panel.x, panel.y) == (220, 20)


def test_py_where_a_connected_inlets_knob_would_be_is_the_background():
    with controls() as (editor, graph, nodes):
        kinds, virtual = listen(editor)
        panel = nodes["panel"]
        sx, sy = port_at(editor, panel, "inlet", "a")
        x, y = sx - 15 - 20, sy                                                                                      # the middle of the pill a free knob would have there
        editor.select(panel.id)
        press(editor, x, y)
        assert editor._drag[0] == "marquee" and editor.selected is None                                              # a press there starts a selection rectangle, nothing else
        move(editor, x, y - 80)
        release(editor, x, y - 80)
        assert panel.knobs["a"] == 0.0 and kinds == [] and (panel.x, panel.y) == (200, 10)
        double_click(editor, x, y)
        assert editor._entry is None and kinds == []
        hover(editor, x, y)
        assert tooltip_texts(editor) == []


def test_py_hovering_a_knob_shows_its_label_and_raw_value():
    with controls() as (editor, graph, nodes):
        panel = nodes["panel"]
        hover(editor, *knob_point(editor, panel, "b"))
        assert tooltip_texts(editor) == ["B: 0.5"]
        box = editor.box(panel)
        text = [i for i in items(editor, "tooltip") if editor.canvas.type(i) == "text"][0]
        assert editor.canvas.bbox(text)[2] <= editor.view.to_screen(box.knob("b").pill[0], 0)[0]                      # to the left of the pill
        hover(editor, *port_at(editor, panel, "inlet", "b"))
        assert tooltip_texts(editor) == ["B"]                                                                        # the port's own label as before
        hover(editor, 700, 600)
        assert tooltip_texts(editor) == []


def test_py_double_clicking_a_free_knob_opens_a_box_to_type_its_value_in_and_enter_sets_it():
    with controls() as (editor, graph, nodes):
        kinds, virtual = listen(editor)
        panel = nodes["panel"]
        x, y = knob_point(editor, panel, "b")
        double_click(editor, x, y)
        assert editor._entry is not None and editor._entry[0].get() == "0.5" and editor.selected == panel.id
        pill = editor.box(panel).knob("b").pill
        info = editor._entry[0].place_info()
        sx, sy = editor.view.to_screen(pill[0], pill[1])
        assert abs(float(info["x"]) - sx) < 1.5 and abs(float(info["y"]) - sy) < 1.5 and float(info["width"]) >= 90 and float(info["height"]) >= 20
        assert editor._entry[0].selection_present()                                                                  # the old text is selected: typing replaces it
        type_into_box(editor, "0.25")
        assert panel.knobs["b"] == 0.25 and editor._entry is None and kinds == ["knob"] and virtual == []
        double_click(editor, x, y)
        type_into_box(editor, " -0.75 ")                                                                             # spaces round the number do not matter
        assert panel.knobs["b"] == -0.75 and kinds == ["knob", "knob"]
        double_click(editor, x, y)
        type_into_box(editor, "-0.75")                                                                               # typing the value it already has is harmless
        assert panel.knobs["b"] == -0.75 and editor._entry is None


def test_py_a_double_click_is_two_presses_within_500_ms_and_5_pixels_by_the_events_own_times():
    with controls() as (editor, graph, nodes):
        x, y = knob_point(editor, nodes["panel"], "b")

        def pair(gap, dx=0, dy=0):
            """Two presses `gap` ms apart, the second `dx`, `dy` pixels off the first, both on the knob; True if a box to type in is open after."""
            _clock[0] += 10000
            base = _clock[0]
            send(editor, "<ButtonPress-1>", x, y, time=base)
            send(editor, "<ButtonRelease-1>", x, y, time=base + 1)
            send(editor, "<ButtonPress-1>", x + dx, y + dy, time=base + gap)
            send(editor, "<ButtonRelease-1>", x + dx, y + dy, time=base + gap + 1)
            opened = editor._entry is not None
            if opened:
                type_into_box(editor, "0.5", key="<Escape>")
            return opened
        assert pair(500) is True and pair(100) is True and pair(0) is True                                           # (500 ms exactly still counts)
        assert pair(501) is False and pair(2000) is False
        assert pair(-100) is False                                                                                   # (an event with an earlier time is not a second press)
        assert pair(100, dx=5, dy=-5) is True and pair(100, dx=-5, dy=5) is True                                      # 5 pixels either way in x and y
        assert pair(100, dx=6) is False and pair(100, dx=-6) is False and pair(100, dy=6) is False and pair(100, dy=-6) is False
        _clock[0] += 10000
        base = _clock[0]                                                                                             # a double click used up: the next press starts afresh
        for offset in (0, 100, 200):
            send(editor, "<ButtonPress-1>", x, y, time=base + offset)
            send(editor, "<ButtonRelease-1>", x, y, time=base + offset + 1)
            if offset == 100:
                assert editor._entry is not None
                type_into_box(editor, "0.5", key="<Escape>")
        assert editor._entry is None and editor._drag is None


def test_py_a_typed_knob_value_that_is_not_a_number_from_minus_one_to_one_is_refused_with_the_reason_and_escape_drops_the_box():
    with controls() as (editor, graph, nodes):
        kinds, virtual = listen(editor)
        panel = nodes["panel"]
        x, y = knob_point(editor, panel, "b")
        for text, wanted in (("abc", "must be a number from -1 to 1, not 'abc'"), ("2", "must be a number from -1 to 1, not 2.0"), ("", "not ''"),
                             ("nan", "must be a number from -1 to 1"), ("-1.0001", "must be a number from -1 to 1")):
            double_click(editor, x, y)
            type_into_box(editor, text)
            assert panel.knobs["b"] == 0.5 and kinds == [] and wanted in editor.message and editor._entry is None, (text, editor.message)
            editor.say("")
        double_click(editor, x, y)
        type_into_box(editor, "0.9", key="<Escape>")                                                                 # Escape drops what was typed
        assert panel.knobs["b"] == 0.5 and editor._entry is None and kinds == []
        double_click(editor, x, y)
        entry = editor._entry[0]
        entry.delete(0, "end")
        entry.insert(0, "0.1")
        press(editor, 700, 600)                                                                                      # a click elsewhere accepts it
        assert panel.knobs["b"] == 0.1 and editor._entry is None and kinds == ["knob"]


# ---------------------------------------------------------------- widgets

def test_py_widgets_are_drawn_from_the_data_buttons_labels_value_boxes_and_a_triangle_on_a_choice_and_unknown_kinds_are_left_out():
    with controls() as (editor, graph, nodes):
        canvas, panel = editor.canvas, nodes["panel"]
        found = widgets_of(editor, panel)
        assert list(found) == ["Controls", "Count", "Gain", "Tag", "File", "Mode", "Reset"]                          # (the unknown kind is not laid out)
        for index in range(7):
            assert items(editor, f"widget:{panel.id}:{index}") != ()
        assert items(editor, f"widget:{panel.id}:7") == ()
        text = lambda tag: canvas.itemcget(one(editor, tag), "text")
        assert text(f"widgetlabel:{panel.id}:0") == "Controls" and items(editor, f"field:{panel.id}:0") == () and items(editor, f"button:{panel.id}:0") == ()
        for index, label, value in ((1, "Count", "3"), (2, "Gain", "0.5"), (3, "Tag", "hi"), (4, "File", ""), (5, "Mode", "sine")):
            assert text(f"widgetlabel:{panel.id}:{index}") == label and text(f"widgetvalue:{panel.id}:{index}") == value
            assert canvas.itemcget(one(editor, f"field:{panel.id}:{index}"), "fill") == theme.FIELD_FILL
            assert items(editor, f"arrow:{panel.id}:{index}") != () if label == "Mode" else items(editor, f"arrow:{panel.id}:{index}") == ()
        assert canvas.itemcget(one(editor, f"button:{panel.id}:6"), "fill") == theme.WIDGET_FILL and text(f"widgettext:{panel.id}:6") == "Reset"
        file_node = nodes["file"]
        assert text(f"widgettext:{file_node.id}:0") == "Open..."
        assert text(f"widgetvalue:{nodes['out'].id}:0") == "out" and text(f"widgetlabel:{nodes['out'].id}:0") == "Name"
        field = canvas.bbox(one(editor, f"field:{panel.id}:1"))                                                      # the value box is on the right of the label, inside the node
        body = canvas.bbox(one(editor, f"body:{panel.id}"))
        assert body[0] < canvas.bbox(one(editor, f"widgetlabel:{panel.id}:1"))[2] <= field[0] and field[2] < body[2]
        editor.view = geo.View(0.4, 50.0, 60.0)                                                                      # 12 px * 0.4 = 4.8 px: below the text threshold
        editor.redraw()
        assert items(editor, "widgetlabel") == () and items(editor, "widgetvalue") == () and items(editor, "widgettext") == ()
        assert len(items(editor, "field")) == 5 + 2 + 1 and len(items(editor, "button")) == 2                        # but the shapes are there (panel 5, boundary nodes 1 + 1, the file's name row)


def test_py_a_long_value_is_cut_to_the_value_box_a_path_keeping_its_end():
    with controls() as (editor, graph, nodes):
        panel = nodes["panel"]
        panel.set("file", "C:/audio/folder/a_long_name.wav")
        panel.set("tag", "a very long string that cannot fit")
        editor.redraw()
        shown = lambda index, node=panel: editor.canvas.itemcget(one(editor, f"widgetvalue:{node.id}:{index}"), "text")
        assert shown(4).startswith("\u2026") and shown(4).endswith("name.wav") and len(shown(4)) <= 15 and shown(4) != panel.settings["file"]
        assert shown(3).startswith("a very") and shown(3).endswith("\u2026") and len(shown(3)) <= 16
        panel.set("tag", "short")
        editor.redraw()
        assert shown(3) == "short"
        preview = graph.add("realtime_preview", x=650, y=10)                                                          # a choice keeps the room of its arrow clear
        preview.set("device", "A very long audio device name")
        editor.redraw()
        box = editor.box(preview)
        device = box.widgets[2]
        room = int((device.x + device.w - device.field_x - 8 - 14) / 7.2)                                             # 8 for the padding, 14 for the arrow
        assert len(shown(2, preview)) == room and shown(2, preview).endswith("\u2026") and room < 14


def test_py_a_button_calls_the_action_listeners_when_released_on_it_and_not_when_released_elsewhere():
    with controls() as (editor, graph, nodes):
        kinds, virtual = listen(editor)
        file_node = nodes["file"]
        centre = lambda node, label: at(editor, widgets_of(editor, node)[label].x + 20, widgets_of(editor, node)[label].y + 11)
        x, y = centre(file_node, "Open...")
        click(editor, x, y)
        assert "no engine is attached" in editor.message and "'open'" in editor.message                               # no engine and no listener yet: it says so
        calls = []
        editor.add_action_listener(lambda node, action: calls.append((node.id, action)))
        index = editor.box(file_node).widgets[0].index
        press(editor, x, y)
        assert editor.canvas.itemcget(one(editor, f"button:{file_node.id}:{index}"), "fill") == theme.WIDGET_FILL_PRESSED and calls == []
        release(editor, x, y)
        assert calls == [(file_node.id, "open")] and editor.selected == file_node.id and (file_node.x, file_node.y) == (450, 300)
        assert editor.canvas.itemcget(one(editor, f"button:{file_node.id}:{index}"), "fill") == theme.WIDGET_FILL
        press(editor, x, y)
        move(editor, x + 150, y + 100)                                                                                # pressed, then moved off: nothing happens (and the node stays)
        release(editor, x + 150, y + 100)
        assert calls == [(file_node.id, "open")] and (file_node.x, file_node.y) == (450, 300)
        panel = nodes["panel"]
        press(editor, *centre(panel, "Reset"))
        release(editor, *field_point(editor, panel, "Count"))                                                         # released over another widget: nothing
        assert calls == [(file_node.id, "open")] and editor._entry is None
        click(editor, *centre(panel, "Reset"))
        assert calls[-1] == (panel.id, "reset") and kinds == [] and virtual == []                                      # pressing a button is not an edit of the graph
        other = []
        editor.say("")
        editor.add_action_listener(lambda node, action: other.append(action))
        click(editor, x, y)
        assert editor.message == ""                                                                                   # (a listener is somewhere to send it: no complaint)
        assert other == ["open"] and calls[-1] == (file_node.id, "open")                                              # every listener is told
        preview = graph.add("realtime_preview", x=650, y=10)                                                          # only the button that is pressed looks pressed
        editor.redraw()
        play, pause = (editor.box(preview).widgets[0], editor.box(preview).widgets[1])
        press(editor, *at(editor, play.x + 20, play.y + 11))
        fill = lambda index: editor.canvas.itemcget(one(editor, f"button:{preview.id}:{index}"), "fill")
        assert fill(0) == theme.WIDGET_FILL_PRESSED and fill(1) == theme.WIDGET_FILL
        release(editor, *at(editor, play.x + 20, play.y + 11))
        click(editor, *at(editor, pause.x + 20, pause.y + 11))
        assert calls[-2:] == [(preview.id, "play"), (preview.id, "pause")]


def test_py_a_text_widget_opens_a_box_over_its_value_and_enter_sets_the_setting_read_as_its_kind():
    with controls() as (editor, graph, nodes):
        kinds, virtual = listen(editor)
        panel = nodes["panel"]
        count = widgets_of(editor, panel)["Count"]
        click(editor, *field_point(editor, panel, "Count"))
        assert editor._entry is not None and editor._entry[0].get() == "3" and editor.selected == panel.id
        info = editor._entry[0].place_info()
        sx, sy = editor.view.to_screen(count.field_x, count.y)
        assert abs(float(info["x"]) - sx) < 1.5 and abs(float(info["y"]) - sy) < 1.5                                   # over the value box
        box = editor._entry[0]
        type_into_box(editor, "42")
        assert not box.winfo_exists()                                                                                 # the box is gone, not just forgotten
        assert panel.settings["count"] == 42 and isinstance(panel.settings["count"], int) and kinds == ["setting"] and virtual == [1]
        assert editor.canvas.itemcget(one(editor, f"widgetvalue:{panel.id}:1"), "text") == "42" and editor._entry is None
        for text, wanted in (("4.5", "must be a whole number, not '4.5'"), ("abc", "must be a whole number"), ("99999999999999999999", "from -9223372036854775808")):
            click(editor, *field_point(editor, panel, "Count"))
            type_into_box(editor, text)
            assert panel.settings["count"] == 42 and wanted in editor.message and kinds == ["setting"], (text, editor.message)
        click(editor, *field_point(editor, panel, "Gain"))
        type_into_box(editor, " 0.25 ")
        assert panel.settings["gain"] == 0.25 and isinstance(panel.settings["gain"], float) and kinds == ["setting", "setting"]
        for text, wanted in (("abc", "must be a number, not 'abc'"), ("nan", "must be a finite number"), ("inf", "must be a finite number")):
            click(editor, *field_point(editor, panel, "Gain"))
            type_into_box(editor, text)
            assert panel.settings["gain"] == 0.25 and wanted in editor.message, (text, editor.message)
        click(editor, *field_point(editor, panel, "Tag"))
        type_into_box(editor, "  two words ")                                                                         # text is taken exactly as typed
        assert panel.settings["tag"] == "  two words "
        click(editor, *field_point(editor, panel, "Tag"))
        type_into_box(editor, "")
        assert panel.settings["tag"] == "" and kinds.count("setting") == 4
        click(editor, *field_point(editor, panel, "File"))
        type_into_box(editor, "relative.wav")
        assert panel.settings["file"] == "" and "absolute path" in editor.message
        click(editor, *field_point(editor, panel, "File"))
        type_into_box(editor, "C:/audio/song.wav")
        assert panel.settings["file"] == "C:/audio/song.wav" and kinds.count("setting") == 5
        before = len(kinds)
        click(editor, *field_point(editor, panel, "Count"))
        type_into_box(editor, "42")                                                                                   # the same value: not a change
        assert len(kinds) == before and editor._entry is None and len(virtual) == before
        click(editor, *field_point(editor, panel, "Count"))
        type_into_box(editor, "7", key="<Escape>")                                                                   # Escape: dropped
        assert panel.settings["count"] == 42 and editor._entry is None
        click(editor, *field_point(editor, nodes["out"], "Name"))                                                     # a boundary node's name is a text widget too
        type_into_box(editor, "left")
        assert nodes["out"].settings["name"] == "left" and kinds[-1] == "setting"


def test_py_a_box_that_is_open_is_accepted_when_something_else_is_pressed_or_the_picture_is_scrolled_and_dropped_with_a_new_graph():
    with controls() as (editor, graph, nodes):
        panel = nodes["panel"]
        click(editor, *field_point(editor, panel, "Count"))
        editor._entry[0].delete(0, "end")
        editor._entry[0].insert(0, "7")
        click(editor, *field_point(editor, panel, "Gain"))                                                            # pressing another widget: the first box is accepted, a second opens
        assert panel.settings["count"] == 7 and editor._entry is not None and editor._entry[0].get() == "0.5"
        editor._entry[0].delete(0, "end")
        editor._entry[0].insert(0, "0.75")
        send(editor, "<MouseWheel>", 300, 300, delta=120)                                                              # scrolling accepts it too
        assert panel.settings["gain"] == 0.75 and editor._entry is None
        click(editor, *field_point(editor, panel, "Gain"))
        editor._entry[0].delete(0, "end")
        editor._entry[0].insert(0, "0.5")
        press(editor, 600, 500, button=2)                                                                              # and so does the middle button that pans
        release(editor, 600, 500, button=2)
        assert panel.settings["gain"] == 0.5 and editor._entry is None
        click(editor, *field_point(editor, panel, "Tag"))
        editor._entry[0].delete(0, "end")
        editor._entry[0].insert(0, "x")
        editor.set_graph(Graph(types=CATALOG))                                                                        # another graph: what was typed is dropped, not given to it
        assert editor._entry is None and panel.settings["tag"] == "hi"
        other = editor.graph.add("vendor.panel", x=100, y=10)
        editor.redraw()
        click(editor, *field_point(editor, other, "Tag"))
        assert editor._entry is not None                                                                              # (left open on purpose: the window is destroyed with it open)


def test_py_a_choice_widget_opens_a_menu_of_its_choices_with_the_current_one_marked_and_choosing_sets_the_setting():
    with controls() as (editor, graph, nodes):
        kinds, virtual = listen(editor)
        shown = []
        editor._popup = lambda menu, x_root, y_root: shown.append((menu, x_root, y_root))
        panel = nodes["panel"]
        mode = widgets_of(editor, panel)["Mode"]
        click(editor, *field_point(editor, panel, "Mode"))
        menu, x_root, y_root = shown[0]
        assert labels(menu) == ["sine", "square", "saw"] and menu.type(0) == "radiobutton"
        assert [editor.getvar(menu.entrycget(i, "variable")) for i in range(3)] == ["sine"] * 3                         # the variable they share holds the current choice
        assert [menu.entrycget(i, "value") for i in range(3)] == ["sine", "square", "saw"]
        sx, sy = editor.view.to_screen(mode.field_x, mode.y + mode.h)
        assert (x_root, y_root) == (int(editor.canvas.winfo_rootx() + sx), int(editor.canvas.winfo_rooty() + sy))        # just under the value box
        menu.invoke(1)                                                                                                # (not the last entry: each entry sets its own choice)
        assert panel.settings["mode"] == "square" and kinds == ["setting"] and virtual == [1]
        editor.redraw()
        assert editor.canvas.itemcget(one(editor, f"widgetvalue:{panel.id}:5"), "text") == "square"
        click(editor, *field_point(editor, panel, "Mode"))
        assert editor.getvar(shown[1][0].entrycget(0, "variable")) == "square"
        shown[1][0].invoke(1)                                                                                         # the same choice again: no change
        assert kinds == ["setting"]
        shown[1][0].invoke(0)
        assert panel.settings["mode"] == "sine" and kinds == ["setting", "setting"]
        device = widgets_of(editor, graph.add("realtime_preview", x=650, y=10))                                       # (a string setting with a fixed list)
        editor.redraw()
        click(editor, *at(editor, device["Device"].field_x + 10, device["Device"].y + 11))
        assert labels(shown[2][0]) == ["(system default)"]


def test_py_a_label_widget_is_part_of_the_node_so_pressing_it_drags_the_node():
    with controls() as (editor, graph, nodes):
        panel = nodes["panel"]
        label = widgets_of(editor, panel)["Controls"]
        x, y = at(editor, label.x + 10, label.y + 10)
        drag(editor, (x, y), (x + 30, y + 20))
        assert (panel.x, panel.y) == (230, 30) and editor._entry is None


# ---------------------------------------------------------------- menus

def test_py_the_node_menu_offers_delete_rename_for_boundary_nodes_and_the_internal_rate_for_nodes_that_have_one():
    with controls() as (editor, graph, nodes):
        shown = catch_menus(editor)
        for key, wanted in (("panel", ["Delete"]), ("filter", ["Delete", "Internal sampling rate..."]), ("out", ["Delete", "Rename..."]),
                            ("src", ["Delete", "Rename..."]), ("file", ["Delete"])):
            box = editor.box(nodes[key])
            right_click(editor, *at(editor, box.x + 20, box.y + 8))                                                  # on the title bar
            assert labels(shown[-1]) == wanted, key
            assert editor.selected == nodes[key].id
        count = len(shown)
        right_click(editor, *field_point(editor, nodes["panel"], "Count"))                                           # on a widget: the node's menu too
        right_click(editor, *port_at(editor, nodes["panel"], "inlet", "b"))                                          # on a free inlet
        right_click(editor, *knob_point(editor, nodes["panel"], "b"))                                                # and on its knob
        right_click(editor, *port_at(editor, nodes["file"], "outlet", "left"))                                       # and on an outlet
        assert len(shown) == count + 4 and all(labels(m) == ["Delete"] for m in shown[count:])


def test_py_deleting_a_node_from_its_menu_removes_it_and_its_connections_and_tells_the_listeners():
    with controls() as (editor, graph, nodes):
        kinds, virtual = listen(editor)
        shown = catch_menus(editor)
        box = editor.box(nodes["filter"])
        right_click(editor, *at(editor, box.x + 20, box.y + 8))
        shown[0].invoke(0)
        assert nodes["filter"].graph is None and nodes["filter"] not in graph.nodes() and len(graph.nodes()) == 4
        assert [(c.outlet.node.id, c.inlet.node.id) for c in graph.connections()] == [(nodes["src"].id, nodes["panel"].id)]       # filter -> out went with it
        assert kinds == ["removed"] and virtual == [1] and editor.selected is None
        editor.redraw()
        assert items(editor, f"body:{box.node_id}") == () and len(items(editor, "body")) == 4 and len(items(editor, "wire")) == 1
        assert all(b.node_id != box.node_id for b in editor.layout())
        right_click(editor, *at(editor, box.x + 20, box.y + 8))                                                      # (nothing is there any more: the add menu)
        assert "Loop protection" in labels(shown[-1])


def test_py_renaming_a_boundary_node_from_its_menu_types_the_name_over_its_title_bar():
    with controls() as (editor, graph, nodes):
        kinds, virtual = listen(editor)
        shown = catch_menus(editor)
        out = nodes["out"]
        box = editor.box(out)
        right_click(editor, *at(editor, box.x + 20, box.y + 8))
        shown[0].invoke(1)
        assert editor._entry is not None and editor._entry[0].get() == "out"
        info = editor._entry[0].place_info()
        sx, sy = editor.view.to_screen(box.x, box.y)
        assert sx <= float(info["x"]) <= sx + box.w and sy <= float(info["y"]) <= sy + box.bar                         # over the title bar
        type_into_box(editor, "left_channel")
        assert out.settings["name"] == "left_channel" and kinds == ["setting"] and virtual == [1]
        assert [b.name for b in graph.boundary_nodes()] == ["left_channel", "src"]
        right_click(editor, *at(editor, box.x + 20, box.y + 8))
        shown[-1].invoke(1)
        assert editor._entry[0].get() == "left_channel"
        type_into_box(editor, "ignored", key="<Escape>")
        assert out.settings["name"] == "left_channel"


def test_py_a_boundary_node_cannot_be_given_no_name_or_the_name_of_another_boundary_node_by_its_box_or_its_menu_and_the_message_says_why():
    with controls() as (editor, graph, nodes):                                                                    # boundary nodes "out" (an outlet) and "src" (an inlet)
        kinds, virtual = listen(editor)
        shown = catch_menus(editor)
        out, src = nodes["out"], nodes["src"]
        twin = graph.add("boundary_outlet", x=700, y=150, name="twin")                                           # a second outlet, for the same-kind case
        editor.redraw()

        def in_the_box(node, text):
            click(editor, *field_point(editor, node, "Name"))
            type_into_box(editor, text)

        def from_the_menu(node, text):
            box = editor.box(node)
            right_click(editor, *at(editor, box.x + 20, box.y + 8))
            shown[-1].invoke(1)
            type_into_box(editor, text)

        for rename in (in_the_box, from_the_menu):
            editor.say("")
            rename(out, "")
            assert out.settings["name"] == "out" and "needs a name" in editor.message and "empty" in editor.message
            editor.say("")
            rename(out, "src")                                                                                   # the name of a boundary node of the other kind...
            assert out.settings["name"] == "out" and 'the boundary name "src" is already used by another boundary node (a boundary inlet)' in editor.message
            editor.say("")
            rename(out, "twin")                                                                                  # ...and of the same kind
            assert out.settings["name"] == "out" and 'the boundary name "twin" is already used by another boundary node (a boundary outlet)' in editor.message
            assert kinds == [] and virtual == []                                                                 # nothing changed, so nothing is announced
        editor.say("")
        in_the_box(out, "out")                                                                                   # its own name again: nothing to refuse, nothing changes
        assert editor.message == "" and kinds == []
        for count, text in enumerate(("Out", "out ", " ", "two words", "ü"), start=1):                           # only no name at all and a name in use are refused: case and spaces make names differ
            in_the_box(out, text)
            assert out.settings["name"] == text and editor.message == "" and kinds == ["setting"] * count and virtual == [1] * count
        in_the_box(twin, "pad")                                                                                  # names that differ from another node's only by a space or by case are other names
        in_the_box(out, "pad ")                                                                                  # (the engine compares the bytes, so these three are three names)
        in_the_box(src, "PAD")
        assert [n.settings["name"] for n in (twin, out, src)] == ["pad", "pad ", "PAD"] and editor.message == ""
        in_the_box(src, "out")                                                                                   # a name that was given up is free for another node
        assert src.settings["name"] == "out" and kinds[-1] == "setting"
        graph.validate()


def test_py_a_long_run_of_adding_renaming_and_deleting_boundary_nodes_never_leaves_an_empty_name_or_a_repeated_one():
    with controls() as (editor, graph, nodes):
        rng = random.Random(20261005)
        names = ["", "default0", "default1", "default2", "out", "src", "a", "b", "A", " ", "c d"]
        accepted = refused = added = deleted = 0
        for step in range(500):
            boundary = [n for n in graph.nodes() if n.type in ("boundary_inlet", "boundary_outlet")]
            roll = rng.random()
            if len(boundary) < 3 or (roll < 0.25 and len(boundary) < 10):
                editor.add_node(rng.choice(["boundary_inlet", "boundary_outlet"]), 10 * step % 700, 500)
                added += 1
            elif roll < 0.85:
                node, text = rng.choice(boundary), rng.choice(names)
                taken = {n.settings["name"] for n in boundary if n is not node}
                result = editor.edit_setting(node, "name", text)
                assert result == (text != "" and text not in taken), (step, text, sorted(taken))                  # the rule, stated here on its own
                accepted, refused = accepted + result, refused + (not result)
            else:
                editor.remove_node(rng.choice(boundary))
                deleted += 1
            graph.validate()                                                                                     # whatever was done, the graph can be compiled
        assert min(accepted, refused, added, deleted) > 20, (accepted, refused, added, deleted)                 # (the run did try all four things, often)


def test_py_the_internal_sampling_rate_item_types_a_whole_number_of_hertz_in_the_range_over_the_title_bar():
    with controls() as (editor, graph, nodes):
        kinds, virtual = listen(editor)
        shown = catch_menus(editor)
        node = nodes["filter"]
        box = editor.box(node)
        right_click(editor, *at(editor, box.x + 20, box.y + 8))
        shown[0].invoke(1)
        assert editor._entry[0].get() == "48000"
        type_into_box(editor, "96000")
        assert node.settings["internal_sampling_rate"] == 96000 and kinds == ["setting"] and virtual == [1]
        for text, wanted in (("0", "from 1 to 384000"), ("384001", "from 1 to 384000"), ("44100.5", "must be a whole number"), ("fast", "must be a whole number")):
            right_click(editor, *at(editor, box.x + 20, box.y + 8))
            shown[-1].invoke(1)
            type_into_box(editor, text)
            assert node.settings["internal_sampling_rate"] == 96000 and wanted in editor.message, (text, editor.message)
        right_click(editor, *at(editor, box.x + 20, box.y + 8))
        shown[-1].invoke(1)
        type_into_box(editor, "384000")
        assert node.settings["internal_sampling_rate"] == 384000 and kinds == ["setting", "setting"]


def test_py_right_clicking_a_connected_inlet_offers_to_disconnect_it():
    with controls() as (editor, graph, nodes):
        kinds, virtual = listen(editor)
        shown = catch_menus(editor)
        panel = nodes["panel"]
        right_click(editor, *port_at(editor, panel, "inlet", "a"))
        assert labels(shown[-1]) == ["Disconnect"] and editor.selected == panel.id
        shown[-1].invoke(0)
        assert graph.connection_into(panel.inlet("a")) is None and kinds == ["disconnected"] and virtual == [1]
        editor.redraw()
        assert len(items(editor, "wire")) == 1 and editor.canvas.itemcget(one(editor, f"knob:{panel.id}:a"), "fill") == theme.KNOB_PILL_FILL      # its knob is live again
        assert editor.connect(nodes["src"].outlet("out"), panel.inlet("a")) and kinds == ["disconnected", "connected"]
        right_click(editor, *port_at(editor, panel, "inlet", "a"))
        assert labels(shown[-1]) == ["Disconnect"]
        shown[-1].invoke(0)
        assert graph.connection_into(panel.inlet("a")) is None
        assert editor.disconnect(panel.inlet("a")) is False and "no connection" in editor.message and kinds[-1] == "disconnected"
        assert editor.disconnect(nodes["out"].inlet("in")) is True


def test_py_right_clicking_a_wire_offers_to_delete_the_connection_and_a_click_beside_it_is_the_background():
    with controls() as (editor, graph, nodes):
        kinds, virtual = listen(editor)
        shown = catch_menus(editor)
        panel, src = nodes["panel"], nodes["src"]
        source, target = editor.box(src).port("outlet", "out"), editor.box(panel).port("inlet", "a")
        flat = geo.wire_points(source.x, source.y, target.x, target.y)
        middle = at(editor, flat[28], flat[29])                                                                       # the 15th of 29 points of the wire
        right_click(editor, *middle)
        assert labels(shown[-1]) == ["Delete connection"]
        right_click(editor, middle[0] - 40, middle[1])                                                                # well beside it: empty background
        assert "Loop protection" in labels(shown[-1]) and graph.connection_into(panel.inlet("a")) is not None
        right_click(editor, middle[0] - 5, middle[1])                                                                 # within 6 pixels: still the wire
        assert labels(shown[-1]) == ["Delete connection"]
        right_click(editor, middle[0] - 8, middle[1])                                                                 # (the wire is nearly vertical here: 8 pixels is clear)
        assert "Loop protection" in labels(shown[-1])
        right_click(editor, *middle)
        shown[-1].invoke(0)
        assert graph.connection_into(panel.inlet("a")) is None and kinds == ["disconnected"] and virtual == [1]
        editor.redraw()
        assert len(items(editor, "wire")) == 1
        editor.view = geo.View(0.5, 50.0, 60.0)                                                                       # the reach is in screen pixels: it holds at other zooms
        editor.redraw()
        wire = editor.canvas.coords(one(editor, f"wire:{nodes['out'].id}:in"))
        i = len(wire) // 2 - 1                                                                                        # the middle vertex of the wire, and the unit vector across it
        along = (wire[i + 2] - wire[i - 2], wire[i + 3] - wire[i - 1])
        length = (along[0] ** 2 + along[1] ** 2) ** 0.5
        across = (along[1] / length, -along[0] / length)
        if across[1] > 0:
            across = (-across[0], -across[1])                                                                         # (the side with empty background)
        right_click(editor, wire[i] + 5 * across[0], wire[i + 1] + 5 * across[1])                                     # 5 screen pixels off: on the wire at any zoom
        assert labels(shown[-1]) == ["Delete connection"]
        right_click(editor, wire[i] + 8 * across[0], wire[i + 1] + 8 * across[1])                                     # 8 pixels off: not
        assert "Loop protection" in labels(shown[-1])


def test_py_the_background_menu_switches_loop_protection_and_refuses_to_turn_it_on_while_there_is_a_loop():
    with controls() as (editor, graph, nodes):
        kinds, virtual = listen(editor)
        panel, filter_node = nodes["panel"], nodes["filter"]
        menu = editor.build_add_menu(0, 0)
        last = menu.index("end")
        assert menu.type(last) == "checkbutton" and menu.entrycget(last, "label") == "Loop protection" and menu.type(last - 1) == "separator"
        assert bool(int(editor.getvar(menu.entrycget(last, "variable")))) is True and graph.loop_protection is True
        menu.invoke(last)
        assert graph.loop_protection is False and kinds == ["loop_protection"] and virtual == [1]
        assert bool(int(editor.getvar(editor.build_add_menu(0, 0).entrycget(last, "variable")))) is False                  # a fresh menu shows the graph's state
        assert editor.connect(panel.outlet("out"), filter_node.inlet("in")) and editor.connect(filter_node.outlet("out"), panel.inlet("b"))
        assert graph.has_loop()
        menu = editor.build_add_menu(0, 0)
        menu.invoke(last)                                                                                             # on again: refused while the loop is there
        assert graph.loop_protection is False and "loop" in editor.message and kinds[-1] == "connected"
        editor.say("")
        assert editor.disconnect(panel.inlet("b"))
        editor.build_add_menu(0, 0).invoke(last)
        assert graph.loop_protection is True and kinds[-1] == "loop_protection" and editor.message == ""
        assert editor.set_loop_protection(True) is True and editor.set_loop_protection(False) is True


def test_py_a_pop_up_menu_is_destroyed_when_the_next_one_is_shown_and_the_editor_edits_settings_and_knobs_through_methods_too():
    with controls() as (editor, graph, nodes):
        panel = nodes["panel"]
        first, second = editor.build_node_menu(panel), editor.build_node_menu(panel)
        shown = []
        first.tk_popup = lambda x, y: shown.append(("first", x, y))                                                   # (a real tk_popup waits for the menu to be dismissed)
        second.tk_popup = lambda x, y: shown.append(("second", x, y))
        editor._popup(first, 10, 20)
        assert first.winfo_exists() and shown == [("first", 10, 20)]
        editor._popup(second, 30, 40)
        assert not first.winfo_exists() and second.winfo_exists() and shown[-1] == ("second", 30, 40)
        assert editor.set_knob(panel, "b", 2) is False and "from -1 to 1" in editor.message and panel.knobs["b"] == 0.5
        assert editor.set_knob(panel, "b", 0.125) is True and panel.knobs["b"] == 0.125
        assert editor.edit_setting(panel, "mode", "square") is True and panel.settings["mode"] == "square"
        assert editor.edit_setting(panel, "mode", "triangle") is False and "must be one of" in editor.message
        editor.remove_node(graph.add("vendor.filter"))
        editor.remove_node(panel)
        assert panel.graph is None
        try:
            editor.remove_node(panel)
        except GraphError:
            pass
        else:
            raise AssertionError("removing a node twice must raise GraphError")
