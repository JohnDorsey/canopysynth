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


def test_py_a_built_in_node_is_laid_out_with_its_title_above_the_body_and_ports_spread_down_the_sides():
    node = node_of("file_read", 100, 50)                    # 0 inlets, 2 outlets; "File read" is short, so the minimum width
    box = geo.layout_node(node)
    assert (box.x, box.y, box.w, box.h, box.bar) == (100, 50, 140, 60, 0) and not box.third_party and box.title == "File read"
    assert [(p.key, p.x, p.y) for p in box.outlets] == [("left", 240, 65.0), ("right", 240, 95.0)] and box.inlets == []
    assert box.title_strip() == (100, 50 - 6 - 16 - 2, 100 + 9 * 16 * 0.6, 50)
    preview = geo.layout_node(node_of("realtime_preview"))   # 3 inlets, 0 outlets; a long title: 16 characters
    assert preview.w == 16 * 16 * 0.6 + 28 and preview.h == 90 and preview.outlets == []
    assert [(p.key, p.x, p.y) for p in preview.inlets] == [("left", 0, 15.0), ("right", 0, 45.0), ("center", 0, 75.0)]
    outlet = geo.layout_node(node_of("boundary_outlet"))     # 1 inlet: in the middle of a body of the minimum 2 rows
    assert outlet.h == 60 and [(p.key, p.y) for p in outlet.inlets] == [("in", 30.0)]
    source = geo.layout_node(node_of("boundary_inlet"))
    assert source.h == 60 and [(p.key, p.x, p.y) for p in source.outlets] == [("out", source.w, 30.0)]


def test_py_a_third_party_node_has_a_title_bar_inside_its_top_and_its_ports_start_below_it():
    node = node_of("py.mixer", 10, 20)                       # 3 inlets, 2 outlets, key "py.mixer" as its name
    box = geo.layout_node(node)
    assert box.third_party and box.bar == 28 and box.w == 140 and box.h == 28 + 90 and box.title == "py.mixer"
    assert [(p.key, p.y) for p in box.inlets] == [("a", 20 + 28 + 15.0), ("b", 20 + 28 + 45.0), ("c", 20 + 28 + 75.0)]
    assert [(p.key, p.y) for p in box.outlets] == [("out", 20 + 28 + 22.5), ("aux", 20 + 28 + 67.5)]
    assert all(p.x == 10 for p in box.inlets) and all(p.x == 150 for p in box.outlets)
    assert box.title_strip() is None
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


def test_py_contains_and_bbox_cover_the_body_a_built_in_title_and_the_ports():
    built_in = geo.layout_node(node_of("file_read", 100, 100))
    assert built_in.contains(100, 100) and built_in.contains(240, 160) and built_in.contains(170, 130)
    assert not built_in.contains(99.9, 130) and not built_in.contains(170, 160.1) and not built_in.contains(241, 130)
    strip = built_in.title_strip()
    assert built_in.contains(strip[0] + 1, strip[1] + 1) and built_in.contains(strip[2] - 1, strip[3] - 1)       # the title text counts as the node
    assert not built_in.contains(strip[2] + 1, strip[1] + 1)                                                        # but not beyond its text
    assert built_in.bbox() == (100 - 9, strip[1], 240 + 9, 160)
    third = geo.layout_node(node_of("py.mixer", 0, 0))
    assert third.contains(70, 5) and third.contains(0, 0) and not third.contains(70, -1)                           # the bar is part of the body
    assert third.bbox() == (-9, 0, 140 + 9, 118)
    assert geo.bounding_box([]) is None
    assert geo.bounding_box([built_in, third]) == (-9, 0, 249, 160)               # (the third-party node reaches higher than the title strip)
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
    assert geo.hit_test(boxes, port.x - 27.9, port.y, 0.5)[0] == "port"              # at zoom 0.5 the radius is 28 world units
    assert geo.hit_test(boxes, port.x - 28.1, port.y, 0.5) is None
    assert geo.hit_test(boxes, port.x - 3.4, port.y, 4.0)[0] == "port"               # at zoom 4 it is 3.5
    assert geo.hit_test(boxes, port.x - 3.6, port.y, 4.0) is None
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


def test_py_hit_testing_edge_cases_exact_radius_nearest_of_two_and_a_title_strips_top():
    box = geo.layout_node(node_of("file_read", 100, 100))
    port = box.outlets[0]
    assert geo.hit_test([box], port.x + theme.PORT_HIT_RADIUS, port.y, 1.0)[0] == "port"               # exactly on the radius counts
    assert geo.hit_test([box], port.x + theme.PORT_HIT_RADIUS + 0.001, port.y, 1.0) is None
    low = geo.layout_node(node_of("realtime_preview", 0, 0))                                            # ports 30 apart; at zoom 0.5 the radius is 28
    first, second = low.inlets[0], low.inlets[1]
    for y, wanted in ((first.y + 10, first), (first.y + 14.9, first), (first.y + 15.1, second), (second.y - 10, second)):
        hit = geo.hit_test([low], first.x - 3, y, 0.5)
        assert hit[0] == "port" and hit[2] is wanted, (y, hit)                                          # both are in reach: the nearer wins
    strip = box.title_strip()
    assert box.contains(strip[0] + 1, strip[1] + 0.5) and not box.contains(strip[0] + 1, strip[1] - 0.5)
    assert not box.contains(strip[0] - 0.5, strip[1] + 5)
    short = geo.rounded_rect(0, 0, 100, 6, 8)                                                           # the radius is limited to half the height too
    assert all(-1e-9 <= y <= 6 + 1e-9 for y in short[1::2])
