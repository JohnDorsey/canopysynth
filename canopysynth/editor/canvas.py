"""The editor widget (design sections 13 and 15): a tkinter Frame that shows a Graph as nodes and wires and edits it.

What it does (plan step 10): draws the nodes (title, ports) and the connections; drag a node to move it; drag from an outlet to an inlet (or from
a free inlet to an outlet) to connect them, with the inlets a wire may go to marked while it is dragged and the ones it may not (an inlet that
already has a connection; a connection that would close a loop while loop protection is on) refused with the reason in the message line;
the mouse wheel zooms around the pointer, Shift+wheel scrolls sideways, Alt+wheel scrolls up and down, a middle-button drag pans; a right click on
the background lists the node types to add. Knobs, widgets and the node and connection menus are plan step 11; the link to the engine step 12.

The editor edits the Graph it was given, and says what it did to whoever asked to be told (`add_listener(function)`: the function gets "added",
"connected" or "moved"; the virtual event <<GraphChanged>> is generated for everything but "moved").

All drawing is done from the Graph and the view by `_draw`, which deletes and redraws everything; a request to draw is coalesced into one at idle
time (`redraw()` draws at once). Items carry tags (`node:<id>`, `port:<id>:<kind>:<key>`, `wire:<id>:<inlet>`, `title:<id>`...) so that tests can
look at what is on the canvas."""
import tkinter as tk
from tkinter import font as tkfont

from ..errors import GraphError
from . import geometry as geo
from . import theme

HIDDEN_TYPES = frozenset({"test_filter"})        # the hidden test-only node type is not in the add-node list (design section 11)
SHIFT = 0x0001
ALT = 0x20000 | 0x0008                           # Alt on Windows; Mod1 elsewhere


class Editor(tk.Frame):
    """A Frame that edits `graph` (a canopysynth.Graph). Options: width and height of the drawing area (default 900 x 600), and the usual Frame ones."""

    def __init__(self, master, graph, **options):
        width, height = options.pop("width", 900), options.pop("height", 600)
        super().__init__(master, background=theme.BACKGROUND, **options)
        self.graph = graph
        self.view = geo.View()
        self.selected = None                       # the ID of the selected node, or None
        self._order = []                           # node IDs in drawing order: the last is on top
        self._drag = None                          # None, or a tuple that says what the left or middle button is dragging
        self._targets = {}                         # while a wire is dragged: (node ID, kind, key) -> None (allowed) or the reason it is not
        self._hover = None                         # (node ID, kind, key) of the port under the pointer
        self._pointer = (0, 0)
        self._listeners = []
        self._dirty = False
        self._fitted = False
        self._fonts = {}
        self._message_after = None
        self._idle_after = None
        self._message_var = tk.StringVar(self)
        self._menu_world = (0.0, 0.0)
        self._label = tk.Label(self, textvariable=self._message_var, anchor="w", background=theme.BACKGROUND, foreground=theme.MESSAGE_TEXT,
                               font=(theme.FONT_FAMILY, 10))
        self._label.pack(side="bottom", fill="x")
        self.canvas = tk.Canvas(self, width=width, height=height, background=theme.BACKGROUND, highlightthickness=0)
        self.canvas.pack(side="top", fill="both", expand=True)
        canvas = self.canvas
        canvas.bind("<ButtonPress-1>", self._press)
        canvas.bind("<B1-Motion>", self._drag_motion)
        canvas.bind("<ButtonRelease-1>", self._release)
        canvas.bind("<Motion>", self._hover_motion)
        canvas.bind("<Leave>", self._leave)
        canvas.bind("<ButtonPress-2>", self._pan_start)
        canvas.bind("<B2-Motion>", self._pan_motion)
        canvas.bind("<ButtonRelease-2>", self._release)
        canvas.bind("<ButtonPress-3>", self._context)
        canvas.bind("<MouseWheel>", self._wheel)
        canvas.bind("<Escape>", self._escape)
        canvas.bind("<Home>", lambda event: self.fit())
        canvas.bind("<Configure>", self._configured)
        self._sync_order()
        self._invalidate()

    # ---- what the host and the tests use ----

    def add_listener(self, function):
        """`function(kind)` is called after every edit the user makes: kind is "added", "connected" or "moved"."""
        self._listeners.append(function)

    @property
    def message(self):
        """The text in the message line (why a connection was refused...)."""
        return self._message_var.get()

    def say(self, text, seconds=6):
        """Shows `text` in the message line for a few seconds."""
        self._message_var.set(text)
        if self._message_after is not None:
            self.after_cancel(self._message_after)
        self._message_after = self.after(int(seconds * 1000), lambda: self._message_var.set("")) if seconds else None

    def set_graph(self, graph):
        """Edits another Graph."""
        self.graph, self.selected, self._order, self._drag, self._hover = graph, None, [], None, None
        self._sync_order()
        self.fit()

    def redraw(self):
        """Draws now (changes otherwise draw at idle time)."""
        self._draw()

    def layout(self):
        """The NodeBox of every node, in drawing order."""
        self._sync_order()
        return [geo.layout_node(self.graph.node(node_id)) for node_id in self._order]

    def box(self, node):
        """The NodeBox of a node of the graph (or of its ID)."""
        node_id = node if isinstance(node, int) else node.id
        for candidate in self.layout():
            if candidate.node_id == node_id:
                return candidate
        raise GraphError(f"the graph has no node {node_id!r}")

    def fit(self):
        """Shows the whole graph (all of it centred, as large as fits)."""
        bbox = geo.bounding_box(self.layout())
        width, height = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        if bbox is None:
            self.view = geo.View()
        else:
            self.view.fit(bbox, width, height)
        self._invalidate()

    def select(self, node_id):
        """Selects a node (or none, with None) and brings it to the front."""
        self.selected = node_id
        if node_id is not None and node_id in self._order:
            self._order.remove(node_id)
            self._order.append(node_id)
        self._invalidate()

    def add_node(self, type_key, wx, wy):
        """Adds a node of this type with its top-left corner at the world point, selects it, and tells the listeners."""
        node = self.graph.add(type_key, x=wx, y=wy)
        self._order.append(node.id)
        self.select(node.id)
        self._change("added")
        return node

    def connect(self, outlet, inlet):
        """Connects the two ports; False, with the reason in the message line, if the graph refuses."""
        reason = self.graph.can_connect(outlet, inlet)
        if reason is not None:
            self.say(reason)
            return False
        self.graph.connect(outlet, inlet)
        self._change("connected")
        return True

    def build_add_menu(self, wx, wy):
        """The right-click menu of the background: every node type that is not hidden, built-in ones first, each adding a node at the world point."""
        menu = tk.Menu(self.canvas, tearoff=0)
        infos = [self.graph.types.get(key) for key in self.graph.types.keys() if key not in HIDDEN_TYPES]
        builtin = sorted((i for i in infos if not geo.is_third_party(i.key)), key=lambda i: i.name.lower())
        other = sorted((i for i in infos if geo.is_third_party(i.key)), key=lambda i: i.name.lower())
        for info in builtin:
            menu.add_command(label=info.name, command=lambda key=info.key: self.add_node(key, wx, wy))
        if builtin and other:
            menu.add_separator()
        for info in other:
            label = info.name if info.realtime_safe else f"{info.name}  (not realtime safe)"
            menu.add_command(label=label, command=lambda key=info.key: self.add_node(key, wx, wy))
        return menu

    # ---- bookkeeping ----

    def _sync_order(self):
        """The drawing order holds exactly the nodes of the graph (the graph may be edited behind the editor's back)."""
        present = {node.id for node in self.graph.nodes()}
        self._order = [node_id for node_id in self._order if node_id in present]
        known = set(self._order)
        self._order += [node.id for node in self.graph.nodes() if node.id not in known]
        if self.selected not in present:
            self.selected = None

    def _change(self, kind):
        self._invalidate()
        for function in list(self._listeners):
            function(kind)
        if kind != "moved":
            self.event_generate("<<GraphChanged>>")

    def _invalidate(self):
        if not self._dirty:
            self._dirty = True
            self._idle_after = self.after_idle(self._draw_if_dirty)

    def _draw_if_dirty(self):
        self._idle_after = None
        if self._dirty and self.winfo_exists():
            self._draw()

    def destroy(self):
        """Cancels the timers still waiting (the message clearing, a drawing at idle time): they would run after the window is gone and Tk would
        print an error for each."""
        for name in ("_message_after", "_idle_after"):
            identifier = getattr(self, name)
            if identifier is not None:
                try:
                    self.after_cancel(identifier)
                except tk.TclError:
                    pass
                setattr(self, name, None)
        super().destroy()

    def _configured(self, event):
        if not self._fitted:
            self._fitted = True
            if self.graph.nodes():
                self.fit()
                return
        self._invalidate()

    def _px(self, units):
        return max(1, round(units * self.view.scale))

    def _font(self, px, bold=False):
        size = max(1, round(px * self.view.scale))
        key = (size, bold)
        if key not in self._fonts:
            self._fonts[key] = tkfont.Font(family=theme.FONT_FAMILY, size=-size, weight="bold" if bold else "normal")
        return self._fonts[key]

    def _text_visible(self, px):
        return px * self.view.scale >= theme.MIN_TEXT_PX

    # ---- drawing ----

    def _visible_world(self):
        """The world rectangle the canvas shows (with a margin), or None while the canvas has no size yet: what is outside it is not drawn."""
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        if width <= 1 or height <= 1:
            return None
        x0, y0 = self.view.to_world(-theme.CULL_MARGIN, -theme.CULL_MARGIN)
        x1, y1 = self.view.to_world(width + theme.CULL_MARGIN, height + theme.CULL_MARGIN)
        return x0, y0, x1, y1

    def _wire(self, x0, y0, x1, y1, color, tags):
        points = self.view.flat_to_screen(geo.wire_points(x0, y0, x1, y1))
        self.canvas.create_line(*points, fill=color, width=self._px(theme.WIRE_WIDTH), capstyle="round", joinstyle="round", tags=tags)

    def _port_state(self, box, port):
        """How a port is drawn: 'plain', 'hover', or, while a wire is dragged, 'target' (it may go there) or 'refused'."""
        if self._drag is not None and self._drag[0] == "wire":
            anchor = self._drag[1]
            if (box.node_id, port.kind, port.key) == (anchor[0], anchor[1], anchor[2]):
                return "target"
            if port.kind == anchor[1]:
                return "refused"
            return "target" if self._targets.get((box.node_id, port.kind, port.key), "") is None else "refused"
        return "hover" if self._hover == (box.node_id, port.kind, port.key) else "plain"

    def _draw(self):
        self._dirty = False
        canvas, view = self.canvas, self.view
        canvas.delete("all")
        boxes = self.layout()
        by_id = {box.node_id: box for box in boxes}
        visible = self._visible_world()
        for connection in self.graph.connections():
            source = by_id[connection.outlet.node.id].port("outlet", connection.outlet.key)
            target = by_id[connection.inlet.node.id].port("inlet", connection.inlet.key)
            if visible is not None and not geo.overlaps(geo.wire_bbox(source.x, source.y, target.x, target.y), visible):
                continue
            self._wire(source.x, source.y, target.x, target.y, theme.WIRE, ("wire", f"wire:{connection.inlet.node.id}:{connection.inlet.key}"))
        for box in boxes:
            if visible is None or geo.overlaps(box.bbox(), visible):
                self._draw_node(box)
        if self._drag is not None and self._drag[0] == "wire":
            self._draw_pending(by_id)
        self._draw_tooltip(by_id)

    def _draw_node(self, box):
        canvas, view = self.canvas, self.view
        node_id, selected = box.node_id, box.node_id == self.selected
        outline = theme.NODE_OUTLINE_SELECTED if selected else theme.NODE_OUTLINE
        width = self._px(theme.OUTLINE_WIDTH + (1 if selected else 0))
        tags = ("node", f"node:{node_id}")
        body = view.flat_to_screen(geo.rounded_rect(box.x, box.y, box.x + box.w, box.y + box.h, theme.CORNER_RADIUS))
        canvas.create_polygon(*body, fill=theme.NODE_FILL, outline=outline, width=width, joinstyle="round", tags=tags + ("body", f"body:{node_id}"))
        if box.third_party:
            colour = theme.TITLE_BAR_REALTIME_SAFE if box.realtime_safe else theme.TITLE_BAR_NOT_REALTIME_SAFE
            bar = view.flat_to_screen(geo.rounded_rect(box.x, box.y, box.x + box.w, box.y + box.bar, theme.CORNER_RADIUS, top_only=True))
            canvas.create_polygon(*bar, fill=colour, outline=outline, width=width, joinstyle="round", tags=tags + ("bar", f"bar:{node_id}"))
            if self._text_visible(theme.TITLE_FONT_PX):
                sx, sy = view.to_screen(box.x + 10, box.y + box.bar / 2)
                canvas.create_text(sx, sy, text=box.title, anchor="w", fill=theme.TITLE_BAR_TEXT, font=self._font(theme.TITLE_FONT_PX, True),
                                   tags=tags + ("title", f"title:{node_id}"))
        elif self._text_visible(theme.TITLE_FONT_PX):
            sx, sy = view.to_screen(box.x, box.y - theme.TITLE_GAP)
            canvas.create_text(sx, sy, text=box.title, anchor="sw", fill=theme.TITLE_TEXT_BUILTIN, font=self._font(theme.TITLE_FONT_PX, True),
                               tags=tags + ("title", f"title:{node_id}"))
        for port in box.ports():
            state = self._port_state(box, port)
            fill = theme.PORT_FILL_REFUSED if state == "refused" else theme.PORT_FILL
            line = {"target": theme.PORT_OUTLINE_TARGET, "hover": theme.PORT_OUTLINE_HOVER}.get(state, theme.PORT_OUTLINE)
            shape = view.flat_to_screen(geo.diamond(port.x, port.y, theme.PORT_RADIUS))
            canvas.create_polygon(*shape, fill=fill, outline=line, width=self._px(theme.OUTLINE_WIDTH), joinstyle="miter",
                                  tags=("port", f"port:{node_id}:{port.kind}:{port.key}"))

    def _draw_pending(self, by_id):
        """The wire being dragged: from its anchor port to the pointer, or to the port it would snap to."""
        node_id, kind, key = self._drag[1][0], self._drag[1][1], self._drag[1][2]
        anchor = by_id[node_id].port(kind, key)
        wx, wy = self.view.to_world(*self._pointer)
        if self._hover is not None and self._targets.get(self._hover, "") is None:
            hover_box = by_id[self._hover[0]]
            snap = hover_box.port(self._hover[1], self._hover[2])
            wx, wy = snap.x, snap.y
        if kind == "outlet":
            self._wire(anchor.x, anchor.y, wx, wy, theme.WIRE_PENDING, ("pending",))
        else:
            self._wire(wx, wy, anchor.x, anchor.y, theme.WIRE_PENDING, ("pending",))

    def _draw_tooltip(self, by_id):
        """The label of the port under the pointer, next to it."""
        if self._hover is None or self._hover[0] not in by_id or not self._text_visible(theme.LABEL_FONT_PX):
            return
        box = by_id[self._hover[0]]
        port = box.port(self._hover[1], self._hover[2])
        if port is None:
            return
        left = port.kind == "inlet"
        sx, sy = self.view.to_screen(port.x + (-1 if left else 1) * (theme.PORT_RADIUS + 6), port.y)
        item = self.canvas.create_text(sx, sy, text=port.label, anchor="e" if left else "w", fill=theme.TOOLTIP_TEXT,
                                       font=self._font(theme.LABEL_FONT_PX), tags=("tooltip",))
        x0, y0, x1, y1 = self.canvas.bbox(item)
        background = self.canvas.create_rectangle(x0 - 3, y0 - 1, x1 + 3, y1 + 1, fill=theme.TOOLTIP_BACKGROUND, outline="", tags=("tooltip",))
        self.canvas.tag_lower(background, item)

    # ---- the mouse ----

    def _hit(self, sx, sy):
        wx, wy = self.view.to_world(sx, sy)
        return geo.hit_test(self.layout(), wx, wy, self.view.scale)

    def _press(self, event):
        self.canvas.focus_set()
        self._pointer = (event.x, event.y)
        hit = self._hit(event.x, event.y)
        if hit is None:
            self.select(None)
            return
        if hit[0] == "port":
            box, port = hit[1], hit[2]
            if port.kind == "inlet" and self.graph.connection_into(self.graph.node(box.node_id).inlet(port.key)) is not None:
                self.say(f"inlet {port.label!r} already has a connection: an inlet takes only one")
                self.select(box.node_id)
                return
            self._start_wire(box, port)
            return
        box = hit[1]
        self.select(box.node_id)
        self._drag = ("node", box.node_id, event.x, event.y)

    def _start_wire(self, box, port):
        """Starts dragging a wire from a port, and works out which ports it could be dropped on (and why not on the others)."""
        node = self.graph.node(box.node_id)
        self._targets = {}
        for other in self.graph.nodes():
            other_box = geo.layout_node(other)
            if port.kind == "outlet":
                for target in other_box.inlets:
                    self._targets[(other.id, "inlet", target.key)] = self.graph.can_connect(node.outlet(port.key), other.inlet(target.key))
            else:
                for source in other_box.outlets:
                    self._targets[(other.id, "outlet", source.key)] = self.graph.can_connect(other.outlet(source.key), node.inlet(port.key))
        self._drag = ("wire", (box.node_id, port.kind, port.key))
        self._invalidate()

    def _drag_motion(self, event):
        self._pointer = (event.x, event.y)
        if self._drag is None:
            return
        if self._drag[0] == "node":
            _, node_id, last_x, last_y = self._drag
            node = self.graph.node(node_id)
            node.x += (event.x - last_x) / self.view.scale
            node.y += (event.y - last_y) / self.view.scale
            self._drag = ("node", node_id, event.x, event.y)
            self._change("moved")
        elif self._drag[0] == "wire":
            self._hover = self._port_key(self._hit(event.x, event.y))
            self._invalidate()
        elif self._drag[0] == "pan":
            self._pan_motion(event)

    def _port_key(self, hit):
        return (hit[1].node_id, hit[2].kind, hit[2].key) if hit is not None and hit[0] == "port" else None

    def _release(self, event):
        drag, self._drag = self._drag, None
        self._pointer = (event.x, event.y)
        if drag is not None and drag[0] == "wire":
            self._finish_wire(drag[1], self._port_key(self._hit(event.x, event.y)))
        self._targets = {}
        self._invalidate()

    def _finish_wire(self, anchor, dropped):
        """The button was released with a wire from `anchor` over `dropped` (a port key or None): connect if it is a port the wire may go to."""
        if dropped is None or dropped[1] == anchor[1]:
            return
        outlet_key, inlet_key = (anchor, dropped) if anchor[1] == "outlet" else (dropped, anchor)
        outlet = self.graph.node(outlet_key[0]).outlet(outlet_key[2])
        inlet = self.graph.node(inlet_key[0]).inlet(inlet_key[2])
        self.connect(outlet, inlet)

    def _hover_motion(self, event):
        self._pointer = (event.x, event.y)
        key = self._port_key(self._hit(event.x, event.y))
        if key != self._hover:
            self._hover = key
            self._invalidate()

    def _leave(self, event):
        if self._hover is not None:
            self._hover = None
            self._invalidate()

    def _pan_start(self, event):
        self._pointer = (event.x, event.y)
        self._drag = ("pan", event.x, event.y)

    def _pan_motion(self, event):
        if self._drag is None or self._drag[0] != "pan":
            return
        self.view.pan(event.x - self._drag[1], event.y - self._drag[2])
        self._drag = ("pan", event.x, event.y)
        self._invalidate()

    def _wheel(self, event):
        notches = event.delta / 120.0
        if event.state & SHIFT:
            self.view.pan(notches * theme.SCROLL_STEP, 0)
        elif event.state & ALT:
            self.view.pan(0, notches * theme.SCROLL_STEP)
        else:
            self.view.zoom_at(event.x, event.y, theme.ZOOM_STEP ** notches)
        self._invalidate()

    def _escape(self, event):
        if self._drag is not None and self._drag[0] == "wire":
            self._drag, self._targets = None, {}
            self._invalidate()

    def _context(self, event):
        if self._hit(event.x, event.y) is None:
            self._menu_world = self.view.to_world(event.x, event.y)
            self._popup(self.build_add_menu(*self._menu_world), event.x_root, event.y_root)

    def _popup(self, menu, x_root, y_root):
        """Shows a menu at a screen position (it waits until the menu is dismissed). A test or a check script replaces this method."""
        try:
            menu.tk_popup(x_root, y_root)
        finally:
            menu.grab_release()
