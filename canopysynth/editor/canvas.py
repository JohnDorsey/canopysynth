"""The editor widget (design sections 13 and 15): a tkinter Frame that shows a Graph as nodes and wires and edits it.

What it does (plan steps 10 and 11): draws the nodes (a title bar, ports, the knob of every unconnected inlet in a pill to the left of the node, the
node's widgets) and the connections; drag a node to move it; drag on the background to select the nodes the rectangle touches, and drag any selected
node to move them all; drag from an outlet to an inlet (or from a free inlet to an outlet) to connect them, with the
inlets a wire may go to marked while it is dragged and the ones it may not (an inlet that already has a connection; a connection that would close a
loop while loop protection is on) refused with the reason in the message line; the knob of an unconnected inlet turns when dragged up or down and
takes a typed value when double-clicked (an inlet that has a connection shows no knob); buttons, text boxes and choices edit the node's settings or call
its actions; the mouse wheel zooms around the pointer, Shift+wheel scrolls sideways, Alt+wheel scrolls up and down, a middle-button drag pans.
Right-click menus: on the background the node types to add and the loop-protection switch, on a node Delete (and Rename... for a boundary node,
Internal sampling rate... for a node that has one), on a connected inlet or on a wire the way to delete the connection. The link to the engine is
plan step 12. A boundary node is added under a name of its own (default0, default1, ...) and may not be given an empty name or one that another boundary
node has (the message line says so): the engine refuses to compile a graph that has either, so the editor never makes one.

The editor edits the Graph it was given, and says what it did to whoever asked to be told (`add_listener(function)`: the function gets "added",
"connected", "disconnected", "removed", "moved", "knob", "setting" or "loop_protection"; the virtual event <<GraphChanged>> is generated for
everything but "moved" and "knob", which change nothing the compiled graph holds; `add_action_listener(function)`: the function gets (node,
action name) when a button is pressed).

All drawing is done from the Graph and the view by `_draw`, which deletes and redraws everything; a request to draw is coalesced into one at idle
time (`redraw()` draws at once). Items carry tags (`node:<id>`, `port:<id>:<kind>:<key>`, `wire:<id>:<inlet>`, `title:<id>`, `knob:<id>:<inlet>`,
`widget:<id>:<index>`...) so that tests can look at what is on the canvas."""
from collections import namedtuple
import ntpath
import os
import tkinter as tk
from tkinter import font as tkfont

from .._descriptor import INTERNAL_RATE_KEY
from ..errors import GraphError
from ..graph import BOUNDARY_KINDS, BOUNDARY_NAME
from . import geometry as geo
from . import theme
from .link import FILE, EngineLink
from .timetext import format_time, parse_time

HIDDEN_TYPES = frozenset({"test_filter"})        # the hidden test-only node type is not in the add-node list (design section 11)
QUIET_CHANGES = frozenset({"moved", "knob"})     # edits that do not generate <<GraphChanged>>: nothing the compiled graph holds has changed
SHIFT = 0x0001
ALT = 0x20000 | 0x0008                           # Alt on Windows; Mod1 elsewhere

Edit = namedtuple("Edit", "kind node_ids detail")
Edit.__doc__ = ("What the user just did, for a listener that needs more than the kind: `kind` as given to the listeners, `node_ids` the IDs of the nodes it "
                "concerned (a tuple), `detail` the inlet key of a knob or the key of a setting, else None.")


class Editor(tk.Frame):
    """A Frame that edits `graph` (a canopysynth.Graph). Options: width and height of the drawing area (default 900 x 600), and the usual Frame ones."""

    def __init__(self, master, graph, **options):
        width, height = options.pop("width", 900), options.pop("height", 600)
        super().__init__(master, background=theme.BACKGROUND, **options)
        self.graph = graph
        self.view = geo.View()
        self._selection = set()                    # the IDs of the selected nodes
        self._order = []                           # node IDs in drawing order: the last is on top
        self._drag = None                          # None, or a tuple that says what the left or middle button is dragging
        self._targets = {}                         # while a wire is dragged: (node ID, kind, key) -> None (allowed) or the reason it is not
        self._hover = None                         # (node ID, kind, key) of the port under the pointer
        self._hover_knob = None                    # (node ID, inlet key) of the knob under the pointer
        self._pointer = (0, 0)
        self.last_edit = None                      # the Edit of the latest change, set before the listeners are called
        self._last_press = None                    # (time, x, y) of the last left press: a second one soon after and near it is a double click
        self._listeners = []
        self._action_listeners = []
        self._links = {}                           # Engine -> EngineLink, for the open engines made over this graph (see `_engine_links`)
        self._notes = {}                           # node ID -> what the engine says about the node, shown under it
        self._time_texts = {}                      # preview node ID -> the text of its time field
        self.file_chooser = None                   # None, or a function(node) -> a path (or "" for none) that replaces the file dialog of "Open..."
        self._tick_after = None
        self._dirty = False
        self._fitted = False
        self._fonts = {}
        self._entry = None                         # None, or (the Entry being typed in, the function that takes its text when it is accepted)
        self._menu = None                          # the last pop-up menu made (destroyed when the next is)
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
        canvas.bind("<ButtonPress-1>", self._press)                  # (double clicks are found by `_press` itself: Tk's own <Double-...> matching is
        canvas.bind("<B1-Motion>", self._drag_motion)                 # not reliable when other events arrive between the two presses)
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
        self._tick_after = self.after(theme.TICK_MS, self._tick)

    # ---- what the host and the tests use ----

    def add_listener(self, function):
        """`function(kind)` is called after every edit the user makes: kind is "added", "connected", "disconnected", "removed", "moved", "knob",
        "setting" or "loop_protection"."""
        self._listeners.append(function)

    def add_action_listener(self, function):
        """`function(node, action)` is called when the user presses a button of a node (action is the button's action name)."""
        self._action_listeners.append(function)

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
        self._close_entry(False)
        self.graph, self._selection, self._order, self._drag, self._hover, self._hover_knob = graph, set(), [], None, None, None
        self._links, self._notes, self._time_texts = {}, {}, {}
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

    @property
    def selection(self):
        """The IDs of the selected nodes, as a frozenset."""
        return frozenset(self._selection)

    @property
    def selected(self):
        """The ID of the selected node when exactly one node is selected, else None."""
        return next(iter(self._selection)) if len(self._selection) == 1 else None

    def select(self, node_id):
        """Selects just this node (or no node, with None) and brings it to the front."""
        self._selection = set() if node_id is None else {node_id}
        if node_id is not None and node_id in self._order:
            self._order.remove(node_id)
            self._order.append(node_id)
        self._invalidate()

    def select_nodes(self, node_ids):
        """Selects exactly these nodes (those the graph has), leaving the drawing order as it is."""
        present = {node.id for node in self.graph.nodes()}
        self._selection = {node_id for node_id in node_ids if node_id in present}
        self._invalidate()

    def add_node(self, type_key, wx, wy):
        """Adds a node of this type with its top-left corner at the world point, selects it, and tells the listeners. A boundary node gets the first of
        the names default0, default1, ... that no boundary node has, since the engine refuses to compile a graph with a boundary node that has no name."""
        settings = {BOUNDARY_NAME: self._unused_boundary_name()} if type_key in BOUNDARY_KINDS else {}
        node = self.graph.add(type_key, x=wx, y=wy, **settings)
        self._order.append(node.id)
        self.select(node.id)
        self._change("added", (node.id,))
        return node

    def _unused_boundary_name(self):
        """The first of default0, default1, ... that no boundary node has (of either kind: every boundary name is unique)."""
        used = {info.name for info in self.graph.boundary_nodes()}
        number = 0
        while f"default{number}" in used:
            number += 1
        return f"default{number}"

    def _boundary_name_refusal(self, node, name):
        """Why this boundary node may not be called `name`, as a sentence, or None if it may: the engine refuses to compile a graph in which a boundary
        name is empty or used by two nodes (of either kind), so the editor does not make one."""
        if name == "":
            return "a boundary node needs a name: the name cannot be empty"
        for info in self.graph.boundary_nodes():
            if info.name == name and info.node_id != node.id:
                return f"the boundary name \"{name}\" is already used by another boundary node (a boundary {info.kind}); boundary names must be unique"
        return None

    def remove_node(self, node):
        """Removes a node and its connections."""
        self.remove_nodes([node])

    def remove_nodes(self, nodes):
        """Removes these nodes and their connections, telling the listeners once ("removed")."""
        nodes = list(nodes)
        ids = tuple(node.id for node in nodes)
        for node in nodes:
            self.graph.remove(node)
        self._sync_order()
        self._change("removed", ids)

    def connect(self, outlet, inlet):
        """Connects the two ports; False, with the reason in the message line, if the graph refuses."""
        reason = self.graph.can_connect(outlet, inlet)
        if reason is not None:
            self.say(reason)
            return False
        self.graph.connect(outlet, inlet)
        self._change("connected", (outlet.node.id, inlet.node.id))
        return True

    def disconnect(self, inlet):
        """Removes the connection into an inlet; False, with a note in the message line, if it has none."""
        connection = self.graph.connection_into(inlet)
        if connection is None:
            self.say(f"inlet {inlet.key!r} has no connection")
            return False
        self.graph.disconnect(connection.outlet, inlet)
        self._change("disconnected", (connection.outlet.node.id, inlet.node.id))
        return True

    def set_knob(self, node, inlet_key, value):
        """Moves the knob of an inlet to `value` (-1 to 1); False, with the reason in the message line, if the graph refuses the value."""
        try:
            node.set_knob(inlet_key, value)
        except GraphError as error:
            self.say(str(error))
            return False
        self._change("knob", (node.id,), inlet_key)
        return True

    def edit_setting(self, node, key, text):
        """Sets a setting from text typed by the user: read as a whole number or a number if the setting is one, taken as it is otherwise. False,
        with the reason in the message line, if the text is not a valid value, or is the name of a boundary node that is empty or that another boundary
        node has. Tells the listeners only if the value changed."""
        kind = node.info.setting[key]["kind"]
        try:
            if kind == "int":
                value = int(text.strip())
            elif kind == "float":
                value = float(text.strip())
            else:
                value = text
        except ValueError:
            self.say(f"the setting {key!r} must be {'a whole number' if kind == 'int' else 'a number'}, not {text.strip()!r}")
            return False
        if node.type in BOUNDARY_KINDS and key == BOUNDARY_NAME:
            reason = self._boundary_name_refusal(node, value)
            if reason is not None:
                self.say(reason)
                return False
        old = node.settings[key]
        try:
            node.set(key, value)
        except GraphError as error:
            self.say(str(error))
            return False
        if node.settings[key] != old:
            self._change("setting", (node.id,), key)
        return True

    def press_button(self, node, action):
        """What pressing a button does: an engine made over the graph does it (the file node's "Open..." first asks for a file, with the file dialog or
        `file_chooser`); the action listeners are called with the node and the action's name (see `add_action_listener`). With no engine and no
        listener it says so."""
        links = self._engine_links()
        if links and node.type == FILE and action == "open":
            self._open_file(node, links)
        else:
            for link in links:
                link.action(node, action)
        if not links and not self._action_listeners:
            self.say(f"no engine is attached to this graph, and nothing else to carry out the action {action!r}: make an Engine over the graph")
            return
        for function in list(self._action_listeners):
            function(node, action)

    def _open_file(self, node, links):
        """The file node's Open...: ask for a WAV file, store its absolute path as the node's path setting (which recompiles), and tell the engines to
        load it (the message of the node says if they could not)."""
        path = self._choose_file(node)
        if not path or not self.edit_setting(node, "path", os.path.abspath(path)):
            return
        for link in links:
            link.open_file(node)

    def _choose_file(self, node):
        if self.file_chooser is not None:
            return self.file_chooser(node)
        from tkinter import filedialog
        current = node.settings.get("path", "")
        return filedialog.askopenfilename(parent=self, title="Open a WAV file", initialdir=os.path.dirname(current) if current else None,
                                          filetypes=[("WAV files", "*.wav"), ("All files", "*.*")])

    # ---- the engines made over the graph ----

    def _engine_links(self):
        """The EngineLinks of the open engines made over this editor's graph (`Graph.engines()`), made when an engine is first seen; the first engine's
        node messages and playback times are the ones shown."""
        engines = self.graph.engines()
        first = not self._links
        self._links = {engine: self._links.get(engine) or EngineLink(self, engine) for engine in engines}
        links = list(self._links.values())
        if first and links:
            links[0].refresh_notes()
            links[0].poll()
        return links

    def _set_notes(self, notes):
        if notes != self._notes:
            self._notes = notes
            self._invalidate()

    def _set_time_text(self, node_id, text):
        """Sets the text of a preview node's time field; True if it changed (and so needs drawing)."""
        if self._time_texts.get(node_id) == text:
            return False
        self._time_texts[node_id] = text
        self._invalidate()
        return True

    def _tick(self):
        """Every TICK_MS: the playback times of the preview nodes of the first engine."""
        self._tick_after = None
        if not self.winfo_exists():
            return
        links = self._engine_links()
        if links:
            links[0].poll()
        self._tick_after = self.after(theme.TICK_MS, self._tick)

    def _type_time(self, node, text):
        try:
            time_ns = parse_time(text)
        except ValueError as error:
            self.say(str(error))
            return
        links = self._engine_links()
        if not links:
            self.say("no engine is attached to this graph: the time has nowhere to go")
            return
        for link in links:
            link.set_time(node, time_ns)

    def rename(self, node):
        """Opens a box to type the name of a boundary node in, over its title bar."""
        box = self.box(node)
        self._open_entry(str(node.settings[BOUNDARY_NAME]), box.x + 6, box.y + 3, box.w - 12, box.bar - 6,
                         lambda text: self.edit_setting(node, BOUNDARY_NAME, text))

    def edit_internal_rate(self, node):
        """Opens a box to type the internal sampling rate of a node in (whole Hz), over its title bar."""
        box = self.box(node)
        self._open_entry(str(node.settings[INTERNAL_RATE_KEY]), box.x + 6, box.y + 3, box.w - 12, box.bar - 6,
                         lambda text: self.edit_setting(node, INTERNAL_RATE_KEY, text))

    def build_add_menu(self, wx, wy):
        """The right-click menu of the background: every node type that is not hidden, built-in ones first, each adding a node at the world point,
        then the switch of loop protection."""
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
        menu.add_separator()
        protection = tk.BooleanVar(menu, value=self.graph.loop_protection)
        menu.add_checkbutton(label="Loop protection", variable=protection, command=lambda: self.set_loop_protection(protection.get()))
        return menu

    def set_loop_protection(self, on):
        """Turns loop protection on or off; on is refused, with the reason in the message line, while the graph holds a loop."""
        try:
            self.graph.loop_protection = on
        except GraphError as error:
            self.say(str(error))
            return False
        self._change("loop_protection")
        return True

    def build_node_menu(self, node):
        """The right-click menu of a node: Delete (Delete selected, which deletes every selected node, when the node is one of several selected);
        Rename... for a boundary node; Internal sampling rate... for a node type that has one."""
        menu = tk.Menu(self.canvas, tearoff=0)
        if node.id in self._selection and len(self._selection) > 1:
            selected = [self.graph.node(node_id) for node_id in sorted(self._selection)]
            menu.add_command(label="Delete selected", command=lambda: self.remove_nodes(selected))
        else:
            menu.add_command(label="Delete", command=lambda: self.remove_node(node))
        if node.type in BOUNDARY_KINDS:
            menu.add_command(label="Rename...", command=lambda: self.rename(node))
        if node.info.has_internal_rate:
            menu.add_command(label="Internal sampling rate...", command=lambda: self.edit_internal_rate(node))
        return menu

    def build_inlet_menu(self, inlet):
        """The right-click menu of a connected inlet: Disconnect."""
        menu = tk.Menu(self.canvas, tearoff=0)
        menu.add_command(label="Disconnect", command=lambda: self.disconnect(inlet))
        return menu

    def build_connection_menu(self, connection):
        """The right-click menu of a wire: Delete connection."""
        menu = tk.Menu(self.canvas, tearoff=0)
        menu.add_command(label="Delete connection", command=lambda: self.disconnect(connection.inlet))
        return menu

    # ---- bookkeeping ----

    def _sync_order(self):
        """The drawing order holds exactly the nodes of the graph (the graph may be edited behind the editor's back)."""
        present = {node.id for node in self.graph.nodes()}
        self._order = [node_id for node_id in self._order if node_id in present]
        known = set(self._order)
        self._order += [node.id for node in self.graph.nodes() if node.id not in known]
        self._selection &= present

    def _change(self, kind, node_ids=(), detail=None):
        self.last_edit = Edit(kind, tuple(node_ids), detail)
        self._invalidate()
        for link in self._engine_links():
            link.edited(self.last_edit)
        for function in list(self._listeners):
            function(kind)
        if kind not in QUIET_CHANGES:
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
        self._entry = None
        for name in ("_message_after", "_idle_after", "_tick_after"):
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

    def _wire_dragging(self):
        return self._drag is not None and self._drag[0] == "wire"

    # ---- typing in a box over the picture ----

    def _open_entry(self, text, wx, wy, width, height, accept):
        """Opens a text box over the world rectangle (wx, wy, width, height) holding `text`, selected. Enter (or leaving the box) hands the text to
        `accept(text)`; Escape drops it. Any box already open is accepted first."""
        self._close_entry(True)
        sx, sy = self.view.to_screen(wx, wy)
        entry = tk.Entry(self.canvas, font=(theme.FONT_FAMILY, 10), bd=0, highlightthickness=1, highlightbackground=theme.FIELD_OUTLINE,
                         highlightcolor=theme.NODE_OUTLINE_SELECTED, background=theme.FIELD_FILL, foreground=theme.WIDGET_TEXT,
                         insertbackground=theme.WIDGET_TEXT, selectbackground="#4A6A8A")
        entry.insert(0, text)
        entry.select_range(0, "end")
        entry.icursor("end")
        entry.place(x=sx, y=sy, width=max(90, width * self.view.scale), height=max(20, height * self.view.scale))
        entry.bind("<Return>", lambda event: self._close_entry(True))
        entry.bind("<KP_Enter>", lambda event: self._close_entry(True))
        entry.bind("<Escape>", lambda event: self._close_entry(False))       # (no <FocusOut> binding: a press, a scroll, a pan or a right click accepts the box
                                                                             # already, and focus moving away on its own - the window manager, another
                                                                             # application - must not close a box the user is typing in)
        self._entry = (entry, accept)
        entry.focus_set()

    def _close_entry(self, accept):
        """Closes the text box, if one is open, handing its text on if `accept`."""
        if self._entry is None:
            return
        entry, function = self._entry
        self._entry = None
        text = entry.get()
        entry.destroy()
        self.canvas.focus_set()
        if accept:
            function(text)

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
        if self._wire_dragging():
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
        if self._wire_dragging():
            self._draw_pending(by_id)
        if self._drag is not None and self._drag[0] == "marquee":
            canvas.create_rectangle(self._drag[1], self._drag[2], *self._pointer, outline=theme.NODE_OUTLINE_SELECTED, dash=theme.MARQUEE_DASH,
                                    tags=("marquee",))
        self._draw_tooltip(by_id)

    def _draw_node(self, box):
        canvas, view = self.canvas, self.view
        node_id, selected = box.node_id, box.node_id in self._selection
        node = self.graph.node(node_id)
        outline = theme.NODE_OUTLINE_SELECTED if selected else theme.NODE_OUTLINE
        width = self._px(theme.OUTLINE_WIDTH + (1 if selected else 0))
        tags = ("node", f"node:{node_id}")
        body = view.flat_to_screen(geo.rounded_rect(box.x, box.y, box.x + box.w, box.y + box.h, theme.CORNER_RADIUS))
        canvas.create_polygon(*body, fill=theme.NODE_FILL, outline=outline, width=width, joinstyle="round", tags=tags + ("body", f"body:{node_id}"))
        sx, sy = view.to_screen(box.x + theme.TITLE_TEXT_X, box.y + box.bar / 2)
        if box.third_party:
            colour = theme.TITLE_BAR_REALTIME_SAFE if box.realtime_safe else theme.TITLE_BAR_NOT_REALTIME_SAFE
            bar = view.flat_to_screen(geo.rounded_rect(box.x, box.y, box.x + box.w, box.y + box.bar, theme.CORNER_RADIUS, top_only=True))
            canvas.create_polygon(*bar, fill=colour, outline=outline, width=width, joinstyle="round", tags=tags + ("bar", f"bar:{node_id}"))
            text_colour = theme.TITLE_BAR_TEXT
        else:                                                    # an uncoloured bar: a thin line under the title that stops short of the edges
            x0, y0 = view.to_screen(box.x + theme.TITLE_RULE_INSET, box.y + box.bar)
            x1, _ = view.to_screen(box.x + box.w - theme.TITLE_RULE_INSET, box.y + box.bar)
            canvas.create_line(x0, y0, x1, y0, fill=theme.TITLE_RULE, width=self._px(1), tags=tags + ("rule", f"rule:{node_id}"))
            text_colour = theme.TITLE_TEXT_BUILTIN
        if self._text_visible(theme.TITLE_FONT_PX):
            canvas.create_text(sx, sy, text=box.title, anchor="w", fill=text_colour, font=self._font(theme.TITLE_FONT_PX, True),
                               tags=tags + ("title", f"title:{node_id}"))
        for knob in box.knobs:
            self._draw_knob(box, node, knob)
        for widget in box.widgets:
            self._draw_widget(box, node, widget)
        for port in box.ports():
            state = self._port_state(box, port)
            fill = theme.PORT_FILL_REFUSED if state == "refused" else theme.PORT_FILL
            line = {"target": theme.PORT_OUTLINE_TARGET, "hover": theme.PORT_OUTLINE_HOVER}.get(state, theme.PORT_OUTLINE)
            shape = view.flat_to_screen(geo.diamond(port.x, port.y, theme.PORT_RADIUS))
            canvas.create_polygon(*shape, fill=fill, outline=line, width=self._px(theme.OUTLINE_WIDTH), joinstyle="miter",
                                  tags=("port", f"port:{node_id}:{port.kind}:{port.key}"))
        if self._notes.get(node_id) and self._text_visible(theme.LABEL_FONT_PX):          # what the engine says about the node, wrapped to its width
            nx, ny = view.to_screen(box.x, box.y + box.h + theme.NOTE_GAP)
            canvas.create_text(nx, ny, text=self._notes[node_id], anchor="nw", fill=theme.MESSAGE_TEXT, font=self._font(theme.LABEL_FONT_PX),
                               width=max(40, box.w * view.scale), tags=("note", f"note:{node_id}"))

    def _draw_knob(self, box, node, knob):
        """The knob of an unconnected inlet (the layout has none for a connected one): a pill to the left of the node holding a round dial with a
        white tick; translucent while a wire is being dragged."""
        view, canvas = self.view, self.canvas
        colours = (theme.KNOB_PILL_FILL, theme.KNOB_PILL_OUTLINE, theme.KNOB_DIAL_FILL, theme.KNOB_DIAL_OUTLINE, theme.KNOB_TICK)
        if self._wire_dragging():
            colours = tuple(theme.blend(colour, theme.BACKGROUND, theme.KNOB_TRANSLUCENT) for colour in colours)
        pill_fill, pill_line, dial_fill, dial_line, tick = colours
        x0, y0, x1, y1 = knob.pill
        pill = view.flat_to_screen(geo.rounded_rect(x0, y0, x1, y1, (y1 - y0) / 2, steps=5))
        canvas.create_polygon(*pill, fill=pill_fill, outline=pill_line, width=self._px(1.5), joinstyle="round",
                              tags=("knob", f"knob:{box.node_id}:{knob.key}"))
        cx0, cy0 = view.to_screen(knob.cx - knob.r, knob.cy - knob.r)
        cx1, cy1 = view.to_screen(knob.cx + knob.r, knob.cy + knob.r)
        canvas.create_oval(cx0, cy0, cx1, cy1, fill=dial_fill, outline=dial_line, width=self._px(1.5), tags=("dial", f"dial:{box.node_id}:{knob.key}"))
        tx0, ty0, tx1, ty1 = geo.knob_tick(knob.cx, knob.cy, knob.r, node.knobs[knob.key])
        sx0, sy0 = view.to_screen(tx0, ty0)
        sx1, sy1 = view.to_screen(tx1, ty1)
        canvas.create_line(sx0, sy0, sx1, sy1, fill=tick, width=self._px(2), capstyle="round", tags=("tick", f"tick:{box.node_id}:{knob.key}"))

    def _draw_widget(self, box, node, widget):
        """A widget of the node: a button, a label, or a label with a box showing a setting's value (a small triangle on a choice)."""
        view, canvas = self.view, self.canvas
        tags = ("widget", f"widget:{box.node_id}:{widget.index}")
        x0, y0 = view.to_screen(widget.x, widget.y)
        x1, y1 = view.to_screen(widget.x + widget.w, widget.y + widget.h)
        middle = (y0 + y1) / 2
        show_text = self._text_visible(theme.LABEL_FONT_PX)
        font = self._font(theme.LABEL_FONT_PX)
        if widget.kind == "button":
            pressed = self._drag is not None and self._drag[0] == "button" and self._drag[1:] == (box.node_id, widget.index)
            shape = view.flat_to_screen(geo.rounded_rect(widget.x, widget.y, widget.x + widget.w, widget.y + widget.h, 5, steps=3))
            canvas.create_polygon(*shape, fill=theme.WIDGET_FILL_PRESSED if pressed else theme.WIDGET_FILL, outline=theme.WIDGET_OUTLINE,
                                  width=self._px(1.5), joinstyle="round", tags=tags + ("button", f"button:{box.node_id}:{widget.index}"))
            if show_text:
                canvas.create_text((x0 + x1) / 2, middle, text=widget.label, fill=theme.WIDGET_TEXT, font=font,
                                   tags=tags + ("widgettext", f"widgettext:{box.node_id}:{widget.index}"))
            return
        if show_text:
            canvas.create_text(x0, middle, text=widget.label, anchor="w", fill=theme.WIDGET_TEXT, font=font,
                               tags=tags + ("widgetlabel", f"widgetlabel:{box.node_id}:{widget.index}"))
        if widget.kind == "label":
            return
        fx0, _ = view.to_screen(widget.field_x, 0)
        canvas.create_rectangle(fx0, y0, x1, y1, fill=theme.FIELD_FILL, outline=theme.FIELD_OUTLINE, width=self._px(1.5),
                                tags=tags + ("field", f"field:{box.node_id}:{widget.index}"))
        arrow = 14 if widget.kind == "choice" else 0
        if widget.kind == "choice":
            ax, half = view.to_screen(widget.x + widget.w - 9, 0)[0], 4 * view.scale
            canvas.create_polygon(ax - half, middle - half / 2, ax + half, middle - half / 2, ax, middle + half, fill=theme.WIDGET_TEXT, outline="",
                                  tags=tags + ("arrow", f"arrow:{box.node_id}:{widget.index}"))
        if show_text:
            text, keep_end = self._widget_text(node, widget)
            room = int((widget.x + widget.w - widget.field_x - 8 - arrow) / (theme.LABEL_FONT_PX * theme.CHAR_WIDTH))
            text = geo.shorten(text, max(1, room), keep_end=keep_end)
            canvas.create_text(fx0 + 4 * view.scale, middle, text=text, anchor="w", fill=theme.WIDGET_TEXT, font=font,
                               tags=tags + ("widgetvalue", f"widgetvalue:{box.node_id}:{widget.index}"))

    def _widget_text(self, node, widget):
        """The text a value box shows, and whether it is cut at its start (a path) when too long: a setting's value; the time of a preview node; the
        file name (not the whole path) of a file node, "(none)" for no file."""
        if widget.kind == "time":
            return self._time_texts.get(node.id, format_time(0)), False
        if widget.kind == "value":
            return ntpath.basename(str(node.settings[widget.setting])) or "(none)", False
        return str(node.settings[widget.setting]), node.info.setting[widget.setting]["kind"] == "path"

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
        """The label of the port under the pointer, next to it; the label and raw position (-1 to 1) of the knob under the pointer or being
        dragged, to the left of its pill."""
        if not self._text_visible(theme.LABEL_FONT_PX):
            return
        if self._drag is not None and self._drag[0] == "knob":
            knob_key = self._drag[1:3]
        else:
            knob_key = self._hover_knob if self._drag is None else None
        box = by_id.get(knob_key[0]) if knob_key is not None else None
        knob = box.knob(knob_key[1]) if box is not None else None
        if knob is not None:
            node = self.graph.node(box.node_id)
            self._tooltip(f"{knob.label}: {geo.format_knob(node.knobs[knob.key])}", knob.pill[0] - 6, knob.cy, "e")
            return
        if self._hover is None or self._hover[0] not in by_id:
            return
        box = by_id[self._hover[0]]
        port = box.port(self._hover[1], self._hover[2])
        if port is None:
            return
        left = port.kind == "inlet"
        self._tooltip(port.label, port.x + (-1 if left else 1) * (theme.PORT_RADIUS + 6), port.y, "e" if left else "w")

    def _tooltip(self, text, wx, wy, anchor):
        sx, sy = self.view.to_screen(wx, wy)
        item = self.canvas.create_text(sx, sy, text=text, anchor=anchor, fill=theme.TOOLTIP_TEXT, font=self._font(theme.LABEL_FONT_PX), tags=("tooltip",))
        x0, y0, x1, y1 = self.canvas.bbox(item)
        background = self.canvas.create_rectangle(x0 - 3, y0 - 1, x1 + 3, y1 + 1, fill=theme.TOOLTIP_BACKGROUND, outline="", tags=("tooltip",))
        self.canvas.tag_lower(background, item)

    # ---- the mouse ----

    def _hit(self, sx, sy):
        wx, wy = self.view.to_world(sx, sy)
        return geo.hit_test(self.layout(), wx, wy, self.view.scale)

    def _is_connected(self, node_id, inlet_key):
        return self.graph.connection_into(self.graph.node(node_id).inlet(inlet_key)) is not None

    def _is_double_click(self, event):
        """Notes this press and says whether it is a double click: the one before it was at most DOUBLE_CLICK_MS milliseconds earlier (by the events'
        own times) and at most DOUBLE_CLICK_PIXELS from it in x and in y."""
        last, self._last_press = self._last_press, (event.time, event.x, event.y)
        return (last is not None and 0 <= event.time - last[0] <= theme.DOUBLE_CLICK_MS
                and abs(event.x - last[1]) <= theme.DOUBLE_CLICK_PIXELS and abs(event.y - last[2]) <= theme.DOUBLE_CLICK_PIXELS)

    def _press(self, event):
        self._close_entry(True)
        self.canvas.focus_set()
        self._pointer = (event.x, event.y)
        double = self._is_double_click(event)
        hit = self._hit(event.x, event.y)
        if hit is None:                                  # the background: a click selects nothing, a drag selects what the rectangle touches
            self.select(None)
            self._drag = ("marquee", event.x, event.y)
            return
        box = hit[1]
        if hit[0] == "knob":
            knob = hit[2]
            self.select(box.node_id)
            if double:                                   # a double click on a free knob: type its value
                self._last_press = None
                node = self.graph.node(box.node_id)
                x0, y0, x1, y1 = knob.pill
                self._open_entry(geo.format_knob(node.knobs[knob.key]), x0, y0, x1 - x0, y1 - y0, lambda text: self._type_knob(node, knob.key, text))
                return
            self._drag = ("knob", box.node_id, knob.key, event.y, self.graph.node(box.node_id).knobs[knob.key])
            self._invalidate()
            return
        if hit[0] == "port":
            port = hit[2]
            if port.kind == "inlet" and self._is_connected(box.node_id, port.key):
                self.say(f"inlet {port.label!r} already has a connection: an inlet takes only one (right-click the inlet to disconnect it)")
                self.select(box.node_id)
                return
            self._start_wire(box, port)
            return
        if hit[0] == "widget":
            self._press_widget(box, hit[2])
            return
        if box.node_id not in self._selection:           # a node of the selection drags the whole selection; any other node is selected alone
            self.select(box.node_id)
        self._drag = ("node", event.x, event.y, box.node_id, False)

    def _press_widget(self, box, widget):
        node = self.graph.node(box.node_id)
        self.select(box.node_id)
        if widget.kind == "button":
            self._drag = ("button", box.node_id, widget.index)
            self._invalidate()
        elif widget.kind == "text":
            self._open_entry(str(node.settings[widget.setting]), widget.field_x, widget.y, widget.x + widget.w - widget.field_x, widget.h,
                             lambda text: self.edit_setting(node, widget.setting, text))
        elif widget.kind == "time":
            self._open_entry(self._widget_text(node, widget)[0], widget.field_x, widget.y, widget.x + widget.w - widget.field_x, widget.h,
                             lambda text: self._type_time(node, text))
        elif widget.kind == "choice":
            self._popup(self._choice_menu(node, widget), *self._root_position(widget.field_x, widget.y + widget.h))

    def _choice_menu(self, node, widget):
        """The menu a choice widget opens: its entries, the current one marked; choosing one sets the setting."""
        menu = tk.Menu(self.canvas, tearoff=0)
        menu.current = tk.StringVar(menu, value=str(node.settings[widget.setting]))          # (kept on the menu: a variable nobody refers to is unset by Tkinter)
        choices = list(widget.choices)
        for link in self._engine_links():                                                     # an engine may know the entries (the machine's audio devices)
            supplied = link.choices(node, widget)
            if supplied is not None:
                choices = supplied
                break
        if menu.current.get() not in choices:                                                 # a value saved earlier that the list no longer has still shows
            choices.append(menu.current.get())
        for choice in choices:
            menu.add_radiobutton(label=choice, value=choice, variable=menu.current,
                                 command=lambda text=choice: self.edit_setting(node, widget.setting, text))
        return menu

    def _root_position(self, wx, wy):
        sx, sy = self.view.to_screen(wx, wy)
        return int(self.canvas.winfo_rootx() + sx), int(self.canvas.winfo_rooty() + sy)

    def _type_knob(self, node, inlet_key, text):
        try:
            value = float(text.strip())
        except ValueError:
            self.say(f"the knob of inlet {inlet_key!r} must be a number from -1 to 1, not {text.strip()!r}")
            return
        self.set_knob(node, inlet_key, value)

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
            _, last_x, last_y, clicked, _moved = self._drag
            for node_id in self._selection:                                  # the selection moves together (it is the one node pressed, unless more were selected)
                node = self.graph.node(node_id)
                node.x += (event.x - last_x) / self.view.scale
                node.y += (event.y - last_y) / self.view.scale
            self._drag = ("node", event.x, event.y, clicked, True)
            self._change("moved", tuple(self._selection))
        elif self._drag[0] == "marquee":
            _, start_x, start_y = self._drag
            x0, y0 = self.view.to_world(start_x, start_y)
            x1, y1 = self.view.to_world(event.x, event.y)
            self.select_nodes(geo.nodes_in_rect(self.layout(), (x0, y0, x1, y1)))
        elif self._drag[0] == "knob":
            _, node_id, key, start_y, start_value = self._drag
            node = self.graph.node(node_id)
            value = geo.knob_value(start_value, start_y - event.y)
            if value != node.knobs[key]:
                self.set_knob(node, key, value)
            self._invalidate()
        elif self._drag[0] == "wire":
            self._hover = self._port_key(self._hit(event.x, event.y))
            self._invalidate()
        elif self._drag[0] == "pan":
            self._pan_motion(event)

    def _port_key(self, hit):
        return (hit[1].node_id, hit[2].kind, hit[2].key) if hit is not None and hit[0] == "port" else None

    def _knob_key(self, hit):
        return (hit[1].node_id, hit[2].key) if hit is not None and hit[0] == "knob" else None

    def _release(self, event):
        drag, self._drag = self._drag, None
        self._pointer = (event.x, event.y)
        if drag is not None and drag[0] == "wire":
            self._finish_wire(drag[1], self._port_key(self._hit(event.x, event.y)))
        elif drag is not None and drag[0] == "node":
            if not drag[4] and len(self._selection) > 1:                   # a click on a node of a group, no drag: the group gives way to that node
                self.select(drag[3])
        elif drag is not None and drag[0] == "button":
            hit = self._hit(event.x, event.y)
            if hit is not None and hit[0] == "widget" and (hit[1].node_id, hit[2].index) == drag[1:]:       # released on the button it was pressed on
                self.press_button(self.graph.node(drag[1]), hit[2].action)
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
        hit = self._hit(event.x, event.y)
        key, knob = self._port_key(hit), self._knob_key(hit)
        if key != self._hover or knob != self._hover_knob:
            self._hover, self._hover_knob = key, knob
            self._invalidate()

    def _leave(self, event):
        if self._hover is not None or self._hover_knob is not None:
            self._hover = self._hover_knob = None
            self._invalidate()

    def _pan_start(self, event):
        self._close_entry(True)
        self._pointer = (event.x, event.y)
        self._drag = ("pan", event.x, event.y)

    def _pan_motion(self, event):
        if self._drag is None or self._drag[0] != "pan":
            return
        self.view.pan(event.x - self._drag[1], event.y - self._drag[2])
        self._drag = ("pan", event.x, event.y)
        self._invalidate()

    def _wheel(self, event):
        self._close_entry(True)
        notches = event.delta / 120.0
        if event.state & SHIFT:
            self.view.pan(notches * theme.SCROLL_STEP, 0)
        elif event.state & ALT:
            self.view.pan(0, notches * theme.SCROLL_STEP)
        else:
            self.view.zoom_at(event.x, event.y, theme.ZOOM_STEP ** notches)
        self._invalidate()

    def _escape(self, event):
        if self._wire_dragging():
            self._drag, self._targets = None, {}
            self._invalidate()

    def _wire_at(self, sx, sy):
        """The Connection whose wire passes within WIRE_HIT_PX screen pixels of the point, or None."""
        wx, wy = self.view.to_world(sx, sy)
        radius = theme.WIRE_HIT_PX / self.view.scale
        by_id = {box.node_id: box for box in self.layout()}
        for connection in self.graph.connections():
            source = by_id[connection.outlet.node.id].port("outlet", connection.outlet.key)
            target = by_id[connection.inlet.node.id].port("inlet", connection.inlet.key)
            x0, y0, x1, y1 = geo.wire_bbox(source.x, source.y, target.x, target.y)
            if x0 - radius <= wx <= x1 + radius and y0 - radius <= wy <= y1 + radius \
                    and geo.wire_distance(source.x, source.y, target.x, target.y, wx, wy) <= radius:
                return connection
        return None

    def _context(self, event):
        """The right-click menus: of a connected inlet (Disconnect), of a node (Delete...), of a wire (Delete connection), of the background."""
        self._close_entry(True)
        self._pointer = (event.x, event.y)
        hit = self._hit(event.x, event.y)
        if hit is None:
            wire = self._wire_at(event.x, event.y)
            if wire is not None:
                menu = self.build_connection_menu(wire)
            else:
                self._menu_world = self.view.to_world(event.x, event.y)
                menu = self.build_add_menu(*self._menu_world)
        else:
            box = hit[1]
            node = self.graph.node(box.node_id)
            inlet_key = hit[2].key if hit[0] == "port" and hit[2].kind == "inlet" else None
            if inlet_key is not None and self._is_connected(box.node_id, inlet_key):
                self.select(box.node_id)
                menu = self.build_inlet_menu(node.inlet(inlet_key))
            else:
                if not (box.node_id in self._selection and len(self._selection) > 1):      # a node of a group keeps the group: its menu can delete it all
                    self.select(box.node_id)
                menu = self.build_node_menu(node)
        self._popup(menu, event.x_root, event.y_root)

    def _popup(self, menu, x_root, y_root):
        """Shows a menu at a screen position (it waits until the menu is dismissed). A test or a check script replaces this method."""
        if self._menu is not None:
            self._menu.destroy()
        self._menu = menu
        try:
            menu.tk_popup(x_root, y_root)
        finally:
            menu.grab_release()
