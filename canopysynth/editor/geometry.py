# SPDX-License-Identifier: GPL-3.0-or-later
"""The editor's geometry, with no Tk in it (so it can be tested without a window): the view (zoom and pan), the layout of a node with its ports,
knobs and widgets, hit testing, and the shapes of wires, knobs and rounded rectangles. Everything here is in world units unless a name says screen."""
import math

from . import theme

WIDGET_KINDS = ("button", "text", "choice", "label")          # the kinds the editor can draw; a descriptor may one day declare others, which are left out
# Rows the editor adds under the descriptor's own widgets, for built-in node types whose design asks for more than a descriptor can say (kind, label, setting):
# the realtime preview's time field (design section 9: "a text field to type a new time", the playback position being no setting) and the file read
# node's file name (the "open" button chooses a file; this row shows which). "time" is typed in, "value" only shows the setting's text.
EXTRA_WIDGETS = {"realtime_preview": (("time", "Time", None),), "file_read": (("value", "File", "path"),)}


class View:
    """The map between world and screen: screen = world * scale + offset."""

    def __init__(self, scale=1.0, ox=0.0, oy=0.0):
        self.scale, self.ox, self.oy = scale, ox, oy

    def to_screen(self, wx, wy):
        return wx * self.scale + self.ox, wy * self.scale + self.oy

    def to_world(self, sx, sy):
        return (sx - self.ox) / self.scale, (sy - self.oy) / self.scale

    def flat_to_screen(self, points):
        """A flat list [x0, y0, x1, y1...] of world points as screen points."""
        s, ox, oy = self.scale, self.ox, self.oy
        return [value * s + (ox if i % 2 == 0 else oy) for i, value in enumerate(points)]

    def zoom_at(self, sx, sy, factor):
        """Zooms by `factor` (limited to the zoom range) keeping the world point under screen point (sx, sy) where it is."""
        new = min(theme.ZOOM_MAX, max(theme.ZOOM_MIN, self.scale * factor))
        real = new / self.scale
        self.ox = sx - (sx - self.ox) * real
        self.oy = sy - (sy - self.oy) * real
        self.scale = new

    def pan(self, dx, dy):
        """Moves the picture by (dx, dy) screen pixels."""
        self.ox += dx
        self.oy += dy

    def fit(self, bbox, width, height):
        """Shows the world rectangle `bbox` = (x0, y0, x1, y1) centred in a screen of width x height, as large as fits (never beyond the zoom
        range, nor beyond 1.5)."""
        x0, y0, x1, y1 = bbox
        inner_w, inner_h = max(1.0, width - 2 * theme.FIT_MARGIN), max(1.0, height - 2 * theme.FIT_MARGIN)
        scale = min(inner_w / max(1.0, x1 - x0), inner_h / max(1.0, y1 - y0), 1.5)
        self.scale = min(theme.ZOOM_MAX, max(theme.ZOOM_MIN, scale))
        self.ox = width / 2 - (x0 + x1) / 2 * self.scale
        self.oy = height / 2 - (y0 + y1) / 2 * self.scale


class PortBox:
    """One port of a node, as laid out: its key and label, its place in world units."""
    __slots__ = ("kind", "key", "label", "x", "y")

    def __init__(self, kind, key, label, x, y):
        self.kind, self.key, self.label, self.x, self.y = kind, key, label, x, y


class KnobBox:
    """The knob of one inlet, as laid out: the pill that holds it, (x0, y0, x1, y1) to the left of the node, and the dial's centre and radius."""
    __slots__ = ("key", "label", "pill", "cx", "cy", "r")

    def __init__(self, key, label, pill, cx, cy, r):
        self.key, self.label, self.pill, self.cx, self.cy, self.r = key, label, pill, cx, cy, r

    def contains(self, wx, wy):
        x0, y0, x1, y1 = self.pill
        return x0 <= wx <= x1 and y0 <= wy <= y1


class WidgetBox:
    """One widget of a node, as laid out: its kind and what it is bound to, its rectangle (x, y, w, h), and for a text or choice widget where its
    value box starts (`field_x`; the label is to the left of it). `index` is the widget's place in the node type's list."""
    __slots__ = ("kind", "index", "label", "setting", "action", "choices", "x", "y", "w", "h", "field_x")

    def __init__(self, kind, index, label, setting, action, choices, x, y, w, h, field_x):
        self.kind, self.index, self.label, self.setting, self.action, self.choices = kind, index, label, setting, action, choices
        self.x, self.y, self.w, self.h, self.field_x = x, y, w, h, field_x

    def interactive(self):
        """A label, and a row that only shows a value, show text: a click on them is a click on the node."""
        return self.kind not in ("label", "value")

    def contains(self, wx, wy):
        return self.x <= wx <= self.x + self.w and self.y <= wy <= self.y + self.h


class NodeBox:
    """A node as laid out: the body rectangle (x, y, w, h), the title bar inside its top `bar` units, the ports, the knobs of the inlets (to the left of
    the body) and the widgets (below the ports)."""

    def __init__(self, node_id, key, title, x, y, w, h, bar, third_party, realtime_safe, inlets, outlets, knobs=(), widgets=()):
        self.node_id, self.key, self.title = node_id, key, title
        self.x, self.y, self.w, self.h, self.bar = x, y, w, h, bar
        self.third_party, self.realtime_safe = third_party, realtime_safe
        self.inlets, self.outlets = inlets, outlets
        self.knobs, self.widgets = list(knobs), list(widgets)

    def ports(self):
        return self.inlets + self.outlets

    def port(self, kind, key):
        for port in (self.inlets if kind == "inlet" else self.outlets):
            if port.key == key:
                return port
        return None

    def knob(self, key):
        for knob in self.knobs:
            if knob.key == key:
                return knob
        return None

    def contains(self, wx, wy):
        """True if the world point is on the node's body (its title bar included)."""
        return self.x <= wx <= self.x + self.w and self.y <= wy <= self.y + self.h

    def bbox(self):
        """The world rectangle of everything the node draws: the body, the ports and the knobs."""
        left = min([self.x - theme.PORT_RADIUS] + [knob.pill[0] for knob in self.knobs])
        return left, self.y, self.x + self.w + theme.PORT_RADIUS, self.y + self.h


def is_third_party(key):
    """Built-in node types have keys without a dot; every other key has one (design section 12)."""
    return "." in key


def _char_px():
    return theme.LABEL_FONT_PX * theme.CHAR_WIDTH


def _widget_width_needed(widget):
    """How wide a node must be, in the body, for this widget (a label, and for text and choice a value box of WIDGET_VALUE_CHARS)."""
    label = len(widget["label"]) * _char_px()
    if widget["kind"] in ("text", "choice", "time", "value"):
        return label + theme.WIDGET_LABEL_GAP + theme.WIDGET_VALUE_CHARS * _char_px() + 14
    return label + 24


def widget_choices(info, widget):
    """The entries a choice widget offers: its own list, or the setting's when it has none (a choice setting's widget may leave the list out)."""
    if widget["choices"]:
        return list(widget["choices"])
    setting = info.setting.get(widget["setting"])
    return list(setting["choices"]) if setting is not None else []


def layout_node(node):
    """The NodeBox of a graph Node: size from its title, its widgets and the number of its ports, the ports spread evenly down each side of the part
    of the body above the widgets, the knob of each inlet that has no connection in a pill to the left of the node, the widgets one to a row below the
    ports."""
    info = node.info
    third = is_third_party(info.key)
    title = info.name
    bar = theme.BAR_HEIGHT
    shown = [(index, widget) for index, widget in enumerate(info.widgets) if widget["kind"] in WIDGET_KINDS]
    for extra, (kind, label, setting) in enumerate(EXTRA_WIDGETS.get(info.key, ())):          # (their indexes continue after the descriptor's widgets)
        shown.append((len(info.widgets) + extra, {"kind": kind, "label": label, "setting": setting, "action": None, "choices": []}))
    width = max([theme.NODE_MIN_WIDTH, len(title) * theme.TITLE_FONT_PX * theme.CHAR_WIDTH + 2 * theme.NODE_PADDING]
                + [_widget_width_needed(widget) + 2 * theme.WIDGET_INSET for _index, widget in shown])
    rows = max(theme.BODY_MIN_ROWS, len(info.inlets), len(info.outlets))
    ports_height = rows * theme.ROW_HEIGHT
    x, y = node.x, node.y
    inlets = [PortBox("inlet", p["key"], p["label"], x, y + bar + (i + 0.5) * ports_height / len(info.inlets)) for i, p in enumerate(info.inlets)]
    outlets = [PortBox("outlet", p["key"], p["label"], x + width, y + bar + (i + 0.5) * ports_height / len(info.outlets)) for i, p in enumerate(info.outlets)]
    knobs = []
    for port in inlets:
        if node.graph.connection_into(node.inlet(port.key)) is not None:      # an inlet that has a connection shows no knob (design section 6)
            continue
        right = x - theme.KNOB_GAP
        pill = (right - theme.KNOB_PILL_WIDTH, port.y - theme.KNOB_PILL_HEIGHT / 2, right, port.y + theme.KNOB_PILL_HEIGHT / 2)
        knobs.append(KnobBox(port.key, port.label, pill, (pill[0] + pill[2]) / 2, port.y, theme.KNOB_RADIUS))
    widgets = []
    top = y + bar + ports_height
    for row, (index, widget) in enumerate(shown):
        wx, wy, ww = x + theme.WIDGET_INSET, top + row * theme.WIDGET_ROW + (theme.WIDGET_ROW - theme.WIDGET_HEIGHT) / 2, width - 2 * theme.WIDGET_INSET
        field_x = wx + len(widget["label"]) * _char_px() + theme.WIDGET_LABEL_GAP
        choices = widget_choices(info, widget) if widget["kind"] == "choice" else list(widget["choices"])
        widgets.append(WidgetBox(widget["kind"], index, widget["label"], widget["setting"], widget["action"], choices, wx, wy, ww, theme.WIDGET_HEIGHT, field_x))
    return NodeBox(node.id, info.key, title, x, y, width, bar + ports_height + len(shown) * theme.WIDGET_ROW, bar, third, info.realtime_safe,
                   inlets, outlets, knobs, widgets)


def hit_test(boxes, wx, wy, scale):
    """What is under the world point: `boxes` is in drawing order (the last is on top). Returns ("knob", box, KnobBox), ("port", box, PortBox),
    ("widget", box, WidgetBox), ("node", box) or None. The topmost node that has the point on a knob, a port, a widget or its body wins; on one
    node a knob wins over a port, a port over a widget, a widget over the body (a label widget is not hit: it is part of the body). The ports'
    hit radius is a number of screen pixels, so it is divided by the zoom."""
    radius = theme.PORT_HIT_RADIUS / scale
    for box in reversed(boxes):
        for knob in box.knobs:
            if knob.contains(wx, wy):
                return ("knob", box, knob)
        best, best_distance = None, radius
        for port in box.ports():
            distance = math.hypot(wx - port.x, wy - port.y)
            if distance <= best_distance:
                best, best_distance = port, distance
        if best is not None:
            return ("port", box, best)
        for widget in box.widgets:
            if widget.interactive() and widget.contains(wx, wy):
                return ("widget", box, widget)
        if box.contains(wx, wy):
            return ("node", box)
    return None


def wire_points(x0, y0, x1, y1, segments=theme.WIRE_SEGMENTS):
    """A wire from an outlet at (x0, y0) to an inlet at (x1, y1) as a flat list of points of a cubic curve that leaves the outlet to the right and
    enters the inlet from the left (the handles are half the horizontal distance long, at least WIRE_MIN_HANDLE)."""
    handle = max(abs(x1 - x0) * 0.5, theme.WIRE_MIN_HANDLE)
    c1x, c2x = x0 + handle, x1 - handle
    points = []
    for i in range(segments + 1):
        t = i / segments
        u = 1.0 - t
        a, b, c, d = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
        points.append(a * x0 + b * c1x + c * c2x + d * x1)
        points.append((a + b) * y0 + (c + d) * y1)                       # (the handles are horizontal: the control points keep y0 and y1)
    return points


def wire_bbox(x0, y0, x1, y1):
    """A world rectangle that holds the whole wire from (x0, y0) to (x1, y1): the box of the curve's four control points (a cubic curve stays inside
    their hull). Used to leave out wires that are off the screen."""
    handle = max(abs(x1 - x0) * 0.5, theme.WIRE_MIN_HANDLE)
    xs = (x0, x1, x0 + handle, x1 - handle)
    return min(xs), min(y0, y1), max(xs), max(y0, y1)


def segment_distance(px, py, ax, ay, bx, by):
    """The distance from the point (px, py) to the segment from (ax, ay) to (bx, by)."""
    dx, dy = bx - ax, by - ay
    length_squared = dx * dx + dy * dy
    t = 0.0 if length_squared == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_squared))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def wire_distance(x0, y0, x1, y1, wx, wy):
    """The distance from the world point to the wire from (x0, y0) to (x1, y1) (to its drawn polyline)."""
    points = wire_points(x0, y0, x1, y1)
    return min(segment_distance(wx, wy, points[i], points[i + 1], points[i + 2], points[i + 3]) for i in range(0, len(points) - 2, 2))


def overlaps(a, b):
    """True if two rectangles (x0, y0, x1, y1) share a point."""
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def nodes_in_rect(boxes, rect):
    """The IDs of the nodes (in the order of `boxes`) whose body touches the world rectangle `rect` = (x, y, x, y), given from any two opposite corners."""
    x0, y0, x1, y1 = rect
    rect = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
    return [box.node_id for box in boxes if overlaps((box.x, box.y, box.x + box.w, box.y + box.h), rect)]


def _arc(cx, cy, r, start, steps):
    return [(cx + r * math.cos(math.radians(start + 90.0 * i / steps)), cy + r * math.sin(math.radians(start + 90.0 * i / steps))) for i in range(steps + 1)]


def rounded_rect(x0, y0, x1, y1, r, steps=6, top_only=False):
    """A flat polygon of the rectangle with rounded corners (only the top two if `top_only`: for the title bar inside a node)."""
    r = min(r, (x1 - x0) / 2, (y1 - y0) / 2)
    corners = [_arc(x1 - r, y0 + r, r, 270, steps)]                       # top right
    corners.append(_arc(x1 - r, y1 - r, r, 0, steps) if not top_only else [(x1, y1)])
    corners.append(_arc(x0 + r, y1 - r, r, 90, steps) if not top_only else [(x0, y1)])
    corners.append(_arc(x0 + r, y0 + r, r, 180, steps))                   # top left
    flat = []
    for corner in corners:
        for x, y in corner:
            flat += [x, y]
    return flat


def diamond(cx, cy, r):
    return [cx, cy - r, cx + r, cy, cx, cy + r, cx - r, cy]


def knob_tick(cx, cy, r, value):
    """The white tick of a knob's dial, (x0, y0, x1, y1) from near the centre to near the rim: straight up for 0, turned KNOB_SWEEP degrees to the
    right for +1 and to the left for -1 (screen y grows downwards)."""
    angle = math.radians(theme.KNOB_SWEEP * value)
    sin, cos = math.sin(angle), math.cos(angle)
    return cx + sin * r * 0.2, cy - cos * r * 0.2, cx + sin * r * 0.85, cy - cos * r * 0.85


def knob_value(start_value, pixels_up):
    """The position of a knob that was at `start_value` and has been dragged `pixels_up` screen pixels up (negative: down), kept in -1..1."""
    return max(-1.0, min(1.0, start_value + 2.0 * pixels_up / theme.KNOB_DRAG_PIXELS))


def format_knob(value):
    """A knob's raw position as shown to the user: three decimals, no trailing zeros ("0.25", "-1", "0")."""
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def shorten(text, max_chars, keep_end=False):
    """`text` cut to at most max_chars characters with an ellipsis where it was cut: at the end, or (keep_end: for a path) at the start."""
    if len(text) <= max_chars:
        return text
    if max_chars <= 1:
        return "…"[:max_chars]
    return "…" + text[len(text) - (max_chars - 1):] if keep_end else text[:max_chars - 1] + "…"


def bounding_box(boxes):
    """The world rectangle that holds every node, or None for none."""
    if not boxes:
        return None
    rects = [box.bbox() for box in boxes]
    return min(r[0] for r in rects), min(r[1] for r in rects), max(r[2] for r in rects), max(r[3] for r in rects)
