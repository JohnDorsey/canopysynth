"""The editor's geometry, with no Tk in it (so it can be tested without a window): the view (zoom and pan), the layout of a node and its ports,
hit testing, and the shapes of wires and rounded rectangles. Everything here is in world units unless a name says screen."""
import math

from . import theme


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


class NodeBox:
    """A node as laid out: the body rectangle (x, y, w, h) and, for a third-party node, the title bar inside its top `bar` units."""

    def __init__(self, node_id, key, title, x, y, w, h, bar, third_party, realtime_safe, inlets, outlets):
        self.node_id, self.key, self.title = node_id, key, title
        self.x, self.y, self.w, self.h, self.bar = x, y, w, h, bar
        self.third_party, self.realtime_safe = third_party, realtime_safe
        self.inlets, self.outlets = inlets, outlets

    def ports(self):
        return self.inlets + self.outlets

    def port(self, kind, key):
        for port in (self.inlets if kind == "inlet" else self.outlets):
            if port.key == key:
                return port
        return None

    def title_width(self):
        return len(self.title) * theme.TITLE_FONT_PX * theme.CHAR_WIDTH

    def title_strip(self):
        """A built-in node's title sits above the body: the rectangle it takes (None for a third-party node, whose title is in its bar)."""
        if self.third_party:
            return None
        return (self.x, self.y - theme.TITLE_GAP - theme.TITLE_FONT_PX - 2, self.x + self.title_width(), self.y)

    def contains(self, wx, wy):
        """True if the world point is on the node: its body, its title bar, or a built-in node's title text."""
        if self.x <= wx <= self.x + self.w and self.y <= wy <= self.y + self.h:
            return True
        strip = self.title_strip()
        return strip is not None and strip[0] <= wx <= strip[2] and strip[1] <= wy <= strip[3]

    def bbox(self):
        """The world rectangle of everything the node draws, ports included."""
        x0, y0, x1, y1 = self.x - theme.PORT_RADIUS, self.y, self.x + self.w + theme.PORT_RADIUS, self.y + self.h
        strip = self.title_strip()
        if strip is not None:
            y0 = min(y0, strip[1])
            x1 = max(x1, strip[2])
        return x0, y0, x1, y1


def is_third_party(key):
    """Built-in node types have keys without a dot; every other key has one (design section 12)."""
    return "." in key


def layout_node(node):
    """The NodeBox of a graph Node: size from its title and the number of its ports, ports spread evenly down each side."""
    info = node.info
    third = is_third_party(info.key)
    title = info.name
    bar = theme.BAR_HEIGHT if third else 0
    width = max(theme.NODE_MIN_WIDTH, len(title) * theme.TITLE_FONT_PX * theme.CHAR_WIDTH + 2 * theme.NODE_PADDING)
    rows = max(theme.BODY_MIN_ROWS, len(info.inlets), len(info.outlets))
    body = rows * theme.ROW_HEIGHT
    x, y = node.x, node.y
    inlets = [PortBox("inlet", p["key"], p["label"], x, y + bar + (i + 0.5) * body / len(info.inlets)) for i, p in enumerate(info.inlets)]
    outlets = [PortBox("outlet", p["key"], p["label"], x + width, y + bar + (i + 0.5) * body / len(info.outlets)) for i, p in enumerate(info.outlets)]
    return NodeBox(node.id, info.key, title, x, y, width, bar + body, bar, third, info.realtime_safe, inlets, outlets)


def hit_test(boxes, wx, wy, scale):
    """What is under the world point: `boxes` is in drawing order (the last is on top). Returns ("port", box, PortBox), ("node", box) or None. The
    topmost node that has the point on a port or on its body wins, and on one node a port wins over the body. The ports' hit radius is a
    number of screen pixels, so it is divided by the zoom."""
    radius = theme.PORT_HIT_RADIUS / scale
    for box in reversed(boxes):
        best, best_distance = None, radius
        for port in box.ports():
            distance = math.hypot(wx - port.x, wy - port.y)
            if distance <= best_distance:
                best, best_distance = port, distance
        if best is not None:
            return ("port", box, best)
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


def overlaps(a, b):
    """True if two rectangles (x0, y0, x1, y1) share a point."""
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


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


def bounding_box(boxes):
    """The world rectangle that holds every node, or None for none."""
    if not boxes:
        return None
    rects = [box.bbox() for box in boxes]
    return min(r[0] for r in rects), min(r[1] for r in rects), max(r[2] for r in rects), max(r[3] for r in rects)
