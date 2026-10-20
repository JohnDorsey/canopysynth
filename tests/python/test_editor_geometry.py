# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests: the editor's geometry (plan step 10), which has no Tk in it: the view (zoom and pan), the layout of nodes and ports, hit testing, wires and
rounded shapes. Expected numbers are worked out by hand from the sizes in canopysynth/editor/theme.py, or from independent references (a
de Casteljau evaluation of the wire's curve)."""
import math
import random

import canopysynth
import graph_dll
from canopysynth import Graph
from canopysynth.editor import geometry as geo
from canopysynth.editor import theme

CATALOG = graph_dll.make_catalog()


def close(a, b, tolerance=1e-9):
    return abs(a - b) <= tolerance


def point_close(p, q, tolerance=1e-9):
    return close(p[0], q[0], tolerance) and close(p[1], q[1], tolerance)


# ---------------------------------------------------------------- the view

def test_py_the_view_maps_world_to_screen_and_back_exactly_enough():
    rng = random.Random(3)
    for _ in range(200):
        view = geo.View(rng.uniform(0.2, 4), rng.uniform(-500, 500), rng.uniform(-500, 500))
        wx, wy = rng.uniform(-1000, 1000), rng.uniform(-1000, 1000)
        sx, sy = view.to_screen(wx, wy)
        assert close(sx, wx * view.scale + view.ox) and close(sy, wy * view.scale + view.oy)
        assert point_close(view.to_world(sx, sy), (wx, wy), 1e-7)
    view = geo.View(2.0, 10.0, -4.0)
    assert view.to_screen(3, 5) == (16.0, 6.0) and view.to_world(16.0, 6.0) == (3.0, 5.0)
    assert view.flat_to_screen([3, 5, 0, 0, -1, 2]) == [16.0, 6.0, 10.0, -4.0, 8.0, 0.0]


def test_py_zooming_keeps_the_world_point_under_the_pointer_where_it_is_also_when_the_limit_is_hit():
    rng = random.Random(4)
    for _ in range(300):
        view = geo.View(rng.uniform(0.3, 3), rng.uniform(-300, 300), rng.uniform(-300, 300))
        sx, sy = rng.uniform(0, 900), rng.uniform(0, 600)
        world = view.to_world(sx, sy)
        view.zoom_at(sx, sy, rng.choice([0.5, 0.9, 1.1, 1.7, 3.0, 0.05, 20.0]))
        assert theme.ZOOM_MIN - 1e-12 <= view.scale <= theme.ZOOM_MAX + 1e-12
        assert point_close(view.to_screen(*world), (sx, sy), 1e-7)
    view = geo.View()
    view.zoom_at(100, 50, 1000.0)
    assert view.scale == theme.ZOOM_MAX
    view.zoom_at(100, 50, 1e-9)
    assert view.scale == theme.ZOOM_MIN
    view = geo.View(2.0, 0.0, 0.0)
    view.zoom_at(10, 10, 1.5)                               # 2 -> 3: the point at world (5, 5) stays at screen (10, 10)
    assert view.scale == 3.0 and view.ox == -5.0 and view.oy == -5.0


def test_py_panning_moves_the_picture_by_screen_pixels():
    view = geo.View(2.0, 5.0, 6.0)
    view.pan(10, -3)
    assert (view.ox, view.oy, view.scale) == (15.0, 3.0, 2.0)
    assert view.to_screen(0, 0) == (15.0, 3.0)


def test_py_fit_centres_the_boxes_as_large_as_fits_within_the_margin_and_the_limits():
    view = geo.View()
    view.fit((0, 0, 400, 200), 880, 480)                    # inner area 800 x 400 (margin 40): 2.0 would fit, 1.5 is the most
    assert view.scale == 1.5
    assert point_close(view.to_screen(200, 100), (440, 240))
    view.fit((0, 0, 2000, 1000), 880, 480)                  # 800 / 2000 = 0.4, 400 / 1000 = 0.4
    assert close(view.scale, 0.4) and point_close(view.to_screen(1000, 500), (440, 240))
    view.fit((0, 0, 100000, 100), 880, 480)
    assert view.scale == theme.ZOOM_MIN
    view.fit((10, 10, 10, 10), 880, 480)                    # a single point: no division by zero
    assert view.scale == 1.5 and point_close(view.to_screen(10, 10), (440, 240))
    view.fit((-300, -100, -100, 100), 200, 200)
    assert point_close(view.to_screen(-200, 0), (100, 100))
    view.fit((0, 0, 400, 400), 880, 480)                    # here the height is what limits: inner 800 x 400, so 1.0 (the width alone would allow 1.5)
    assert view.scale == 1.0 and point_close(view.to_screen(200, 200), (440, 240))
    view.fit((0, 0, 1600, 100), 880, 480)                   # and here the width: 800 / 1600
    assert view.scale == 0.5 and point_close(view.to_screen(800, 50), (440, 240))


# ---------------------------------------------------------------- the layout of nodes

def node_of(key, x=0.0, y=0.0, graph=None):
    graph = graph or Graph(types=CATALOG)
    return graph.add(key, x=x, y=y)


def test_py_a_built_in_node_has_a_title_bar_inside_its_top_ports_down_the_sides_and_its_widgets_in_rows_below_them():
    node = node_of("file_read", 100, 50)                    # 0 inlets, 2 outlets, a button and the row that shows the file's name (added by the editor)
    box = geo.layout_node(node)
    assert (box.x, box.y, box.bar) == (100, 50, 28) and not box.third_party and box.title == "File read"
    assert close(box.w, 4 * 7.2 + 6 + 14 * 7.2 + 14 + 20)       # the file row (a label and a value box) is what the node's width has to fit: 169.6
    assert box.h == 28 + 2 * 30 + 2 * 30                     # the bar, two port rows, two widget rows
    assert [(p.key, p.y) for p in box.outlets] == [("left", 93.0), ("right", 123.0)] and all(close(p.x, 100 + box.w) for p in box.outlets)
    assert box.inlets == [] and box.knobs == [] and len(box.widgets) == 2
    button, file_row = box.widgets
    assert (button.kind, button.label, button.action, button.setting, button.index) == ("button", "Open...", "open", None, 0)
    assert (button.x, button.y, button.h) == (110, 50 + 28 + 60 + 4, 22) and close(button.w, box.w - 20)         # a row of 30 holds a widget of 22, 4 above and 4 below
    assert (file_row.kind, file_row.label, file_row.setting, file_row.index, file_row.action) == ("value", "File", "path", 1, None)
    assert file_row.y == 50 + 28 + 60 + 30 + 4 and not file_row.interactive()                                  # (its index continues after the descriptor's widgets)
    preview = geo.layout_node(node_of("realtime_preview"))   # 3 inlets, 0 outlets, three widgets and the time field; a long title (16 characters) but a wider Device widget
    assert close(preview.w, 6 * 7.2 + 6 + 14 * 7.2 + 14 + 2 * 10)         # its label, the gap, 14 characters of value, the arrow room, the insets
    assert preview.w > 16 * 16 * 0.6 + 28 and preview.h == 28 + 90 + 4 * 30 and preview.outlets == []
    assert [(p.key, p.x, p.y) for p in preview.inlets] == [("left", 0, 43.0), ("right", 0, 73.0), ("center", 0, 103.0)]
    assert [(w.kind, w.label, w.index) for w in preview.widgets] == [("button", "Play", 0), ("button", "Pause", 1), ("choice", "Device", 2), ("time", "Time", 3)]
    assert [w.y for w in preview.widgets] == [122, 152, 182, 212] and preview.widgets[3].interactive() and preview.widgets[3].setting is None
    device = preview.widgets[2]
    assert device.setting == "device" and device.choices == ["(system default)"] and close(device.field_x, 10 + 6 * 7.2 + 6) and close(device.w, preview.w - 20)
    outlet = geo.layout_node(node_of("boundary_outlet"))     # 1 inlet in the middle of the 2 minimum rows, and a text widget for its name
    assert outlet.h == 28 + 60 + 30 and [(p.key, p.y) for p in outlet.inlets] == [("in", 58.0)]
    assert [(w.kind, w.label, w.setting) for w in outlet.widgets] == [("text", "Name", "name")] and close(outlet.w, 15 * 9.6 + 28)         # (here the 15-character title is wider than the widget needs: 169.6)
    source = geo.layout_node(node_of("boundary_inlet"))
    assert source.h == 28 + 60 + 30 and [(p.key, p.x, p.y) for p in source.outlets] == [("out", source.w, 58.0)]


def test_py_a_third_party_node_has_a_title_bar_inside_its_top_and_its_ports_start_below_it():
    node = node_of("py.mixer", 10, 20)                       # 3 inlets, 2 outlets, key "py.mixer" as its name
    box = geo.layout_node(node)
    assert box.third_party and box.bar == 28 and box.w == 140 and box.h == 28 + 90 and box.title == "py.mixer"
    assert [(p.key, p.y) for p in box.inlets] == [("a", 20 + 28 + 15.0), ("b", 20 + 28 + 45.0), ("c", 20 + 28 + 75.0)]
    assert [(p.key, p.y) for p in box.outlets] == [("out", 20 + 28 + 22.5), ("aux", 20 + 28 + 67.5)]
    assert all(p.x == 10 for p in box.inlets) and all(p.x == 150 for p in box.outlets)
    assert box.widgets == []                                 # (the test type declares none)
    assert box.realtime_safe is False and geo.layout_node(node_of("py.versioned")).realtime_safe is False         # (neither test type is flagged)
    assert geo.layout_node(node_of("file_read")).realtime_safe is True                                          # the built-in ones are
    assert geo.is_third_party("vendor.name") and geo.is_third_party("a.b.c") and not geo.is_third_party("file_read")


def test_py_a_wide_title_makes_a_wide_node_and_many_ports_a_tall_one():
    from engine_dll import PyNodeType
    import engine_dll as e
    long_name = PyNodeType("vendor.x", inlets=[(f"i{n}", 0.0) for n in range(7)], outlets=["a"], at=lambda ctx, outlet, t: 0.0)
    long_name.type.name = b"A very long node title here"
    rig = e.Rig(long_name)
    try:
        graph = Graph(types=canopysynth.NodeTypes.from_registry(rig.registry, e.lib))
        box = geo.layout_node(graph.add("vendor.x", x=0, y=0))
        assert box.w == len("A very long node title here") * 16 * 0.6 + 28
        assert box.h == 28 + 7 * 30 and len(box.inlets) == 7
        assert [p.y for p in box.inlets] == [28 + (i + 0.5) * 30 for i in range(7)]
        assert box.outlets[0].y == 28 + 7 * 30 / 2                       # one outlet: in the middle
    finally:
        rig.close()


def test_py_contains_and_bbox_cover_the_body_with_its_bar_the_ports_and_the_knobs():
    built_in = geo.layout_node(node_of("boundary_outlet", 100, 100))                # body (100, 100) to (100 + 172, 100 + 118); one inlet, which has no wire: a knob
    right = 100 + built_in.w
    assert built_in.contains(100, 100) and built_in.contains(right, 218) and built_in.contains(170, 130)
    assert not built_in.contains(99.9, 130) and not built_in.contains(170, 218.1) and not built_in.contains(right + 0.1, 130) and not built_in.contains(170, 99.9)
    assert built_in.bbox() == (100 - 55, 100, right + 9, 218)                       # the knob's pill reaches out to the left, the ports by their radius
    no_inlets = geo.layout_node(node_of("file_read", 100, 100))                     # no inlet, so no knob: the box is only as wide as the ports reach
    assert no_inlets.bbox() == (100 - 9, 100, 100 + no_inlets.w + 9, 100 + 148)
    third = geo.layout_node(node_of("py.mixer", 0, 0))
    assert third.contains(70, 5) and third.contains(0, 0) and not third.contains(70, -1)                           # the bar is part of the body
    assert third.bbox() == (-55, 0, 140 + 9, 118)                                   # the knobs' pills reach out to the left of the ports: 15 + 40
    assert geo.bounding_box([]) is None
    assert geo.bounding_box([built_in, third]) == (-55, 0, right + 9, 218)
    assert geo.bounding_box([built_in]) == built_in.bbox()


# ---------------------------------------------------------------- hit testing

def test_py_hit_testing_prefers_ports_over_bodies_and_the_topmost_node_and_scales_the_port_radius_with_the_zoom():
    low = geo.layout_node(node_of("py.mixer", 0, 0))
    high = geo.layout_node(node_of("py.mixer", 100, 40))         # overlaps `low` (140 wide, 118 high) and is drawn after it: on top
    boxes = [low, high]
    assert geo.hit_test(boxes, 120, 60, 1.0)[0:2] == ("node", high)                 # where both bodies are: the one on top
    assert geo.hit_test(boxes, 20, 20, 1.0)[0:2] == ("node", low)
    assert geo.hit_test(boxes, 500, 500, 1.0) is None
    port = low.inlets[1]                                                             # a port on the left edge of `low`
    hit = geo.hit_test(boxes, port.x, port.y, 1.0)
    assert hit[0] == "port" and hit[1] is low and hit[2] is port
    inside_radius = geo.hit_test(boxes, port.x - 13.9, port.y, 1.0)                  # 14 screen pixels at zoom 1
    assert inside_radius is not None and inside_radius[0] == "port"
    outside = geo.hit_test(boxes, port.x - 14.1, port.y, 1.0)
    assert outside is None                                                           # (left of the node: nothing there)
    assert geo.hit_test(boxes, port.x + 27.9, port.y, 0.5)[0] == "port"              # at zoom 0.5 the radius is 28 world units (measured into the body)
    assert geo.hit_test(boxes, port.x + 28.1, port.y, 0.5)[0:2] == ("node", low)
    assert geo.hit_test(boxes, port.x + 3.4, port.y, 4.0)[0] == "port"               # at zoom 4 it is 3.5
    assert geo.hit_test(boxes, port.x + 3.6, port.y, 4.0)[0:2] == ("node", low)
    near = geo.hit_test(boxes, low.inlets[0].x, low.inlets[0].y + 14, 1.0)       # between two ports 30 apart: the nearer wins
    assert near[0] == "port" and near[2] is low.inlets[0]
    near = geo.hit_test(boxes, low.inlets[0].x, low.inlets[0].y + 16, 1.0)
    assert near[0] == "port" and near[2] is low.inlets[1]
    # a port of a node below, covered by a node above, is not reachable where the node above has its body... unless it is within the port radius
    covered = geo.layout_node(node_of("file_read", 0, 200))
    cover = geo.layout_node(node_of("boundary_outlet", 100, 190))                    # over the right edge (x = 140) of `covered`
    p = covered.outlets[0]
    assert geo.hit_test([covered, cover], p.x - 2, p.y, 1.0)[0:2] == ("node", cover)
    assert geo.hit_test([cover, covered], p.x - 2, p.y, 1.0)[0] == "port"


# ---------------------------------------------------------------- shapes

def de_casteljau(points, t):
    while len(points) > 1:
        points = [((1 - t) * a[0] + t * b[0], (1 - t) * a[1] + t * b[1]) for a, b in zip(points, points[1:])]
    return points[0]


def test_py_a_wire_is_the_cubic_curve_with_horizontal_handles_from_the_outlet_to_the_inlet():
    for x0, y0, x1, y1 in ((0, 0, 300, 100), (0, 0, 20, -80), (100, 50, -200, 300), (5, 5, 5, 5), (0, 0, 1000, 0)):
        flat = geo.wire_points(x0, y0, x1, y1)
        points = list(zip(flat[0::2], flat[1::2]))
        assert len(points) == theme.WIRE_SEGMENTS + 1
        assert point_close(points[0], (x0, y0)) and point_close(points[-1], (x1, y1))
        handle = max(abs(x1 - x0) * 0.5, theme.WIRE_MIN_HANDLE)
        controls = [(x0, y0), (x0 + handle, y0), (x1 - handle, y1), (x1, y1)]
        for i, p in enumerate(points):
            assert point_close(p, de_casteljau(controls, i / theme.WIRE_SEGMENTS), 1e-9), (x0, y0, x1, y1, i)
    flat = geo.wire_points(0, 0, 300, 100, segments=4)
    assert len(flat) == 10
    flat = geo.wire_points(0, 0, 300, 100)
    xs, ys = flat[0::2], flat[1::2]
    assert all(b >= a for a, b in zip(xs, xs[1:])) and all(b >= a for a, b in zip(ys, ys[1:]))                 # a forward wire never goes back
    assert abs(ys[1] - ys[0]) < 1.5 and abs(ys[-1] - ys[-2]) < 1.5                                               # and starts and ends nearly flat


def test_py_a_rounded_rectangle_stays_inside_its_rectangle_touches_all_four_sides_and_can_have_square_bottom_corners():
    flat = geo.rounded_rect(10, 20, 110, 80, 8)
    points = list(zip(flat[0::2], flat[1::2]))
    assert all(10 - 1e-9 <= x <= 110 + 1e-9 and 20 - 1e-9 <= y <= 80 + 1e-9 for x, y in points)
    for wanted in ((10, 28), (10, 72), (110, 28), (110, 72), (18, 20), (102, 20), (18, 80), (102, 80)):               # where the straight sides begin and end
        assert any(point_close(p, wanted, 1e-9) for p in points), wanted
    assert not any(point_close(p, (10, 20)) or point_close(p, (110, 80)) for p in points)                           # the corners are cut
    assert len(points) == 4 * 7
    # the arcs are circular: each corner point is at distance 8 from the corner's centre
    assert all(close(math.hypot(x - 102, y - 28), 8.0, 1e-9) for x, y in points[:7])
    top = geo.rounded_rect(10, 20, 110, 80, 8, top_only=True)
    top_points = list(zip(top[0::2], top[1::2]))
    assert (110, 80) in top_points and (10, 80) in top_points                                                       # square bottom corners
    assert len(top_points) == 2 * 7 + 2
    tiny = geo.rounded_rect(0, 0, 6, 100, 8)                                                                        # the radius is limited to half the width
    assert all(-1e-9 <= x <= 6 + 1e-9 for x in tiny[0::2])
    assert geo.diamond(10, 20, 9) == [10, 11, 19, 20, 10, 29, 1, 20]


def test_py_the_wire_box_holds_the_whole_curve_and_overlap_is_plain_rectangle_overlap():
    rng = random.Random(6)
    for _ in range(300):
        x0, y0, x1, y1 = (rng.uniform(-800, 800) for _ in range(4))
        left, top, right, bottom = geo.wire_bbox(x0, y0, x1, y1)
        flat = geo.wire_points(x0, y0, x1, y1)
        assert all(left - 1e-9 <= x <= right + 1e-9 for x in flat[0::2]) and all(top - 1e-9 <= y <= bottom + 1e-9 for y in flat[1::2])
        assert left <= min(x0, x1) and right >= max(x0, x1) and top == min(y0, y1) and bottom == max(y0, y1)
    assert geo.wire_bbox(0, 0, 10, 0) == (-50, 0, 60, 0)                              # the handles are 60 long: out to 60 from the start, back to -50 from the end
    assert geo.wire_bbox(0, 5, 400, -5) == (0, -5, 400, 5)                            # a long wire: the handles (200) stay inside the span
    assert geo.overlaps((0, 0, 10, 10), (10, 10, 20, 20)) and geo.overlaps((0, 0, 10, 10), (5, 5, 6, 6)) and geo.overlaps((5, 5, 6, 6), (0, 0, 10, 10))
    assert not geo.overlaps((0, 0, 10, 10), (10.1, 0, 20, 10)) and not geo.overlaps((0, 0, 10, 10), (0, 10.1, 10, 20))
    assert not geo.overlaps((0, 0, 10, 10), (-5, -5, -0.1, 3)) and not geo.overlaps((20, 0, 30, 10), (0, 0, 19.9, 10))


def test_py_hit_testing_edge_cases_exact_radius_and_nearest_of_two():
    box = geo.layout_node(node_of("file_read", 100, 100))
    port = box.outlets[0]
    assert geo.hit_test([box], port.x + theme.PORT_HIT_RADIUS, port.y, 1.0)[0] == "port"               # exactly on the radius counts
    assert geo.hit_test([box], port.x + theme.PORT_HIT_RADIUS + 0.001, port.y, 1.0) is None
    low = geo.layout_node(node_of("realtime_preview", 0, 0))                                            # ports 30 apart; at zoom 0.5 the radius is 28
    first, second = low.inlets[0], low.inlets[1]
    for y, wanted in ((first.y + 10, first), (first.y + 14.9, first), (first.y + 15.1, second), (second.y - 10, second)):
        hit = geo.hit_test([low], first.x - 3, y, 0.5)
        assert hit[0] == "port" and hit[2] is wanted, (y, hit)                                          # both are in reach: the nearer wins
    short = geo.rounded_rect(0, 0, 100, 6, 8)                                                           # the radius is limited to half the height too
    assert all(-1e-9 <= y <= 6 + 1e-9 for y in short[1::2])


# ---------------------------------------------------------------- knobs and widgets (plan step 11)

def descriptor(widgets=(), settings=(), inlets=(("a", 0.0),), outlets=("out",)):
    """A node type as `_descriptor.read_node_type` would give it, written by hand (no DLL needed): key vendor.w, title "W"."""
    return {"key": "vendor.w", "name": "W", "type_version": 1, "realtime_safe": True, "has_internal_rate": False,
            "inlets": [{"key": k, "label": k.upper(), "default_knob": v} for k, v in inlets],
            "outlets": [{"key": k, "label": k} for k in outlets],
            "settings": list(settings), "widgets": list(widgets), "scratch_buffers": 0, "handlers": {}}


def widget(kind, label, setting=None, action=None, choices=()):
    return {"kind": kind, "label": label, "setting": setting, "action": action, "choices": list(choices)}


def test_py_every_inlet_has_a_knob_in_a_pill_to_the_left_of_the_node_level_with_its_port():
    box = geo.layout_node(node_of("py.mixer", 10, 20))              # inlets a, b, c at y = 63, 93, 123 on x = 10
    assert [k.key for k in box.knobs] == ["a", "b", "c"]
    for knob, port in zip(box.knobs, box.inlets):
        assert knob.pill == (10 - 15 - 40, port.y - 13, 10 - 15, port.y + 13)         # 40 wide and 26 high, its right end 15 left of the node's edge
        assert knob.cy == port.y and knob.cx == 10 - 15 - 20 and knob.r == 10 and knob.label == port.label
    assert box.knob("b") is box.knobs[1] and box.knob("zzz") is None
    assert box.knobs[1].pill[1] - box.knobs[0].pill[3] == 4                         # neighbouring pills do not touch (30 apart, 26 high)
    assert geo.layout_node(node_of("file_read")).knobs == []                        # no inlets, no knobs


def test_py_a_knob_is_hit_inside_its_pill_before_its_port_and_a_node_on_top_covers_it():
    box = geo.layout_node(node_of("py.mixer", 100, 20))
    knob, port = box.knobs[0], box.inlets[0]
    hit = geo.hit_test([box], knob.cx, knob.cy, 1.0)
    assert hit[0] == "knob" and hit[1] is box and hit[2] is knob
    x0, y0, x1, y1 = knob.pill
    assert geo.hit_test([box], x0 + 0.1, knob.cy, 1.0)[0] == "knob" and geo.hit_test([box], x0 - 0.1, knob.cy, 1.0) is None
    assert geo.hit_test([box], x1 - 0.1, y1 - 0.1, 1.0)[0] == "knob" and geo.hit_test([box], knob.cx, y0 - 0.1, 1.0) is None
    assert geo.hit_test([box], port.x - 14, port.y, 1.0)[0] == "port"               # the port's reach at zoom 1 stops short of the pill (15 away)
    assert geo.hit_test([box], port.x - 15.5, port.y, 1.0)[0] == "knob"
    assert geo.hit_test([box], port.x - 20, port.y, 0.5)[0] == "knob"               # at zoom 0.5 the port's reach (28) overlaps the pill: the knob wins
    cover = geo.layout_node(node_of("py.mixer", 30, 20))                            # its body (30 to 170) covers the pill (45 to 85)
    assert geo.hit_test([box, cover], knob.cx, knob.cy, 1.0)[0:2] == ("node", cover)
    assert geo.hit_test([cover, box], knob.cx, knob.cy, 1.0)[0] == "knob"


def test_py_widgets_are_laid_out_in_rows_a_label_widget_is_not_hit_and_a_kind_the_editor_does_not_know_is_left_out():
    settings = [{"key": "mode", "kind": "choice", "default": 1, "choices": ["a", "b"]}]
    catalog = canopysynth.NodeTypes([descriptor(widgets=[widget("button", "Go", action="go"), widget("screen", "Picture"), widget("label", "Hello"),
                                                         widget("choice", "Mode", setting="mode")], settings=settings)])
    box = geo.layout_node(Graph(types=catalog).add("vendor.w", x=0, y=0))
    assert [(w.kind, w.index) for w in box.widgets] == [("button", 0), ("label", 2), ("choice", 3)]       # the index keeps the place in the type's list
    assert box.h == 28 + 60 + 3 * 30 and close(box.w, 4 * 7.2 + 6 + 14 * 7.2 + 14 + 20)
    assert [w.y for w in box.widgets] == [92, 122, 152] and all(w.x == 10 and close(w.w, box.w - 20) for w in box.widgets)
    assert box.widgets[2].choices == ["a", "b"]                                      # the widget lists none: the setting's choices
    go, label = box.widgets[0], box.widgets[1]
    hit = geo.hit_test([box], go.x + 5, go.y + 5, 1.0)
    assert hit[0] == "widget" and hit[2] is go and go.interactive()
    assert not label.interactive() and geo.hit_test([box], label.x + 5, label.y + 5, 1.0)[0:2] == ("node", box)
    assert geo.hit_test([box], go.x + 5, go.y - 1, 1.0)[0:2] == ("node", box)         # the gap between rows is the node
    long_label = "A button with a long label"                                           # a button's label sets the node's width when it is the widest thing in it
    wide = geo.layout_node(Graph(types=canopysynth.NodeTypes([descriptor(widgets=[widget("button", long_label, action="go")])])).add("vendor.w"))
    assert close(wide.w, len(long_label) * 7.2 + 24 + 20) and wide.widgets[0].w == wide.w - 20
    only_unknown = canopysynth.NodeTypes([descriptor(widgets=[widget("screen", "Picture")])])
    plain = geo.layout_node(Graph(types=only_unknown).add("vendor.w"))
    assert plain.widgets == [] and plain.h == 28 + 60 and plain.w == 140              # nothing is laid out for it, not even a row


def test_py_the_dial_turns_135_degrees_each_way_and_a_drag_moves_a_knob_across_its_range_in_200_pixels():
    s = math.sqrt(0.5)
    x0, y0, x1, y1 = geo.knob_tick(100, 50, 10, 0.0)
    assert point_close((x0, y0), (100, 48)) and point_close((x1, y1), (100, 41.5))        # straight up: from 0.2 to 0.85 of the radius above the centre
    assert point_close(geo.knob_tick(100, 50, 10, 1.0)[2:], (100 + s * 8.5, 50 + s * 8.5))     # +1: 135 degrees to the right: down and to the right
    assert point_close(geo.knob_tick(100, 50, 10, -1.0)[2:], (100 - s * 8.5, 50 + s * 8.5))
    angle = math.radians(67.5)
    assert point_close(geo.knob_tick(100, 50, 10, 0.5)[2:], (100 + math.sin(angle) * 8.5, 50 - math.cos(angle) * 8.5))
    assert point_close(geo.knob_tick(100, 50, 10, 0.5)[:2], (100 + math.sin(angle) * 2, 50 - math.cos(angle) * 2))          # and it starts 0.2 of the radius from the centre
    assert geo.knob_value(0.0, 100) == 1.0 and geo.knob_value(0.0, 50) == 0.5 and geo.knob_value(0.0, -25) == -0.25
    assert geo.knob_value(0.25, 0) == 0.25 and geo.knob_value(0.9, 100) == 1.0 and geo.knob_value(-0.9, -100) == -1.0
    assert geo.knob_value(0.5, -150) == -1.0 and geo.knob_value(-0.5, 150) == 1.0


def test_py_a_knob_shows_its_raw_value_in_three_decimals_without_trailing_zeros():
    shown = [geo.format_knob(v) for v in (0.25, -1.0, 0.0, 0.1234, -0.0001, 0.9996, 1.0, -0.5, 0.05, 1e-9)]
    assert shown == ["0.25", "-1", "0", "0.123", "0", "1", "1", "-0.5", "0.05", "0"]


def test_py_text_too_long_for_its_box_is_cut_with_an_ellipsis_at_the_end_or_for_a_path_at_the_start():
    assert geo.shorten("hello", 10) == "hello" and geo.shorten("abc", 3) == "abc" and geo.shorten("", 4) == ""
    assert geo.shorten("hello world", 8) == "hello w\u2026" and geo.shorten("abcd", 3) == "ab\u2026"
    assert geo.shorten("C:/a/b/song.wav", 8, keep_end=True) == "\u2026ong.wav" and geo.shorten("C:/a/b/song.wav", 15, keep_end=True) == "C:/a/b/song.wav"
    assert geo.shorten("abcdef", 1) == "\u2026" and geo.shorten("abcdef", 0) == ""


def test_py_the_distance_to_a_wire_is_the_distance_to_its_drawn_line():
    assert close(geo.segment_distance(5, 5, 0, 0, 10, 0), 5) and close(geo.segment_distance(-3, 4, 0, 0, 10, 0), 5)     # beside it, and beyond its end
    assert close(geo.segment_distance(13, 4, 0, 0, 10, 0), 5) and close(geo.segment_distance(3, 4, 1, 1, 1, 1), math.hypot(2, 3))   # (a segment of one point)
    assert close(geo.wire_distance(0, 0, 300, 0, 150, 5), 5) and close(geo.wire_distance(0, 0, 300, 0, -10, 0), 10)         # a straight wire
    flat = geo.wire_points(0, 0, 300, 100)
    for i in (0, 6, 14, 20, 28):
        assert geo.wire_distance(0, 0, 300, 100, flat[2 * i], flat[2 * i + 1]) < 1e-9, i                              # on its own points
    assert geo.wire_distance(0, 0, 300, 100, flat[28], flat[29] - 8) <= 8 and geo.wire_distance(0, 0, 300, 100, 150, 500) > 400


def test_py_a_colour_blended_over_another_is_the_weighted_mean_of_each_channel():
    assert theme.blend("#FFFFFF", "#000000", 0.5) == "#808080" and theme.blend("#FF8000", "#000000", 0.4) == "#663300"
    assert theme.blend("#123456", "#ABCDEF", 1.0) == "#123456" and theme.blend("#123456", "#ABCDEF", 0.0) == "#ABCDEF"
    assert theme.blend("#000000", "#262626", 0.25) == "#1C1C1C"                      # 0.75 * 0x26 = 28.5 -> 28 = 0x1C (rounded to even)


def test_py_the_not_realtime_safe_bar_is_a_muted_vermillion_darker_than_the_first_peach_the_author_saw():
    import colorsys

    def hsv(colour):
        return colorsys.rgb_to_hsv(*(int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)))
    first_peach, vermillion = "#EDB48F", "#E34234"                                   # (the colour of step 10, and vermillion itself)
    hue, saturation, value = hsv(theme.TITLE_BAR_NOT_REALTIME_SAFE)
    old_hue, old_saturation, old_value = hsv(first_peach)
    vermillion_hue, vermillion_saturation, _ = hsv(vermillion)
    assert value < old_value                                                            # darker
    assert abs(hue - vermillion_hue) < abs(old_hue - vermillion_hue)                    # closer to vermillion
    assert old_saturation < saturation < vermillion_saturation - 0.1                    # more colour than the peach, but not fully saturated
    assert theme.TITLE_BAR_NOT_REALTIME_SAFE != theme.TITLE_BAR_REALTIME_SAFE


# ---------------------------------------------------------------- hidden knobs and rectangle selection (after step 11)

def test_py_an_inlet_that_has_a_connection_has_no_knob_in_the_layout_and_gets_it_back_when_disconnected():
    graph = Graph(types=CATALOG)
    source = graph.add("file_read", x=0, y=0)
    mixer = graph.add("py.mixer", x=100, y=20)                                       # inlets a, b, c
    sink = graph.add("boundary_outlet", x=400, y=0)                                   # one inlet: "in"
    assert [k.key for k in geo.layout_node(mixer).knobs] == ["a", "b", "c"]
    graph.connect(source.outlet("left"), mixer.inlet("b"))
    box = geo.layout_node(mixer)
    assert [k.key for k in box.knobs] == ["a", "c"] and box.knob("b") is None
    assert [p.key for p in box.inlets] == ["a", "b", "c"]                            # (the port stays, with its place)
    gone = (100 - 15 - 20, box.port("inlet", "b").y)                                  # where b's knob was: nothing is hit there
    assert geo.hit_test([box], *gone, 1.0) is None
    graph.connect(source.outlet("right"), mixer.inlet("a"))
    graph.connect(source.outlet("right"), mixer.inlet("c"))
    assert geo.layout_node(mixer).knobs == [] and geo.layout_node(mixer).bbox()[0] == 100 - 9       # no knob at all: the box is only as wide as the ports
    graph.connect(mixer.outlet("out"), sink.inlet("in"))
    assert geo.layout_node(sink).knobs == [] and geo.layout_node(sink).bbox()[0] == 400 - 9
    graph.disconnect(source.outlet("right"), mixer.inlet("c"))
    assert [k.key for k in geo.layout_node(mixer).knobs] == ["c"] and geo.layout_node(mixer).bbox()[0] == 100 - 55


def test_py_a_rectangle_selects_the_nodes_whose_bodies_it_touches_whatever_corner_it_was_dragged_from():
    graph = Graph(types=CATALOG)
    a = geo.layout_node(graph.add("file_read", x=0, y=0))                              # body 0..140 x 0..118
    b = geo.layout_node(graph.add("py.mixer", x=300, y=0))                             # 300..440 x 0..118, knobs left of it
    c = geo.layout_node(graph.add("file_read", x=0, y=300))                            # 0..140 x 300..418
    boxes = [a, b, c]
    assert geo.nodes_in_rect(boxes, (-10, -10, 10, 10)) == [a.node_id] and geo.nodes_in_rect(boxes, (10, 10, -10, -10)) == [a.node_id]
    assert geo.nodes_in_rect(boxes, (10, -10, -10, 10)) == [a.node_id] and geo.nodes_in_rect(boxes, (-10, 10, 10, -10)) == [a.node_id]
    assert geo.nodes_in_rect(boxes, (a.x + a.w, 50, a.x + a.w + 60, 60)) == [a.node_id]   # touching an edge counts...
    assert geo.nodes_in_rect(boxes, (a.x + a.w + 0.1, 50, a.x + a.w + 60, 60)) == []   # ...and a hair beyond does not
    assert geo.nodes_in_rect(boxes, (50, 148.1, 60, 299.9)) == []
    assert geo.nodes_in_rect(boxes, (0, 0, 440, 118)) == [a.node_id, b.node_id]
    assert geo.nodes_in_rect(boxes, (-5, 200, 500, 500)) == [c.node_id]
    assert geo.nodes_in_rect(boxes, (20, 20, 30, 30)) == [a.node_id]                    # a rectangle wholly inside a body
    assert geo.nodes_in_rect(boxes, (-50, -50, 600, 600)) == [a.node_id, b.node_id, c.node_id]
    assert geo.nodes_in_rect(boxes, (250, 40, 270, 60)) == []                           # where b's knob pill is: it is not part of the body
    assert geo.nodes_in_rect([b, a], (-10, -10, 500, 50)) == [b.node_id, a.node_id]     # in the order given
    assert geo.nodes_in_rect([], (0, 0, 10, 10)) == []
