"""What an editor does with an Engine made over the same Graph (plan step 12; design sections 8, 9, 11 and 15). No drawing in here: the Editor draws, this
class talks to the engine.

An `Engine(graph)` registers itself with the graph, and every Editor of the graph finds it there (`Graph.engines()`) and makes one EngineLink for it. The
link
  - recompiles and swaps (`Engine.update`) after every edit that changes what an engine compiles (a node added, removed, connected, disconnected, a setting
    changed); a graph that cannot be compiled (a boundary node without a name, which a host can put into the Graph and the editor never makes) leaves the
    engine running the previous one, and the editor's message line says why, until the next compile works;
  - writes a knob move to the engine at once, with no recompile;
  - sends the buttons of the nodes to the engine ("play", "pause", "device" of the preview node, "open" of the file node), and the time typed in the preview
    node's time field;
  - after every install or action, asks each node for what it says about itself and each preview node for its warning (design section 9) and gives the
    editor the text to show under the node;
  - polls the playback time of the preview nodes for the time field;
  - calls `Engine.collect` after nodes are deleted, so that the device of a deleted preview node is closed.
The editor shows the first engine's notes and times; every engine gets the updates, the knobs and the buttons."""
from ..errors import BoundaryError, GraphError
from .timetext import format_time

PREVIEW = "realtime_preview"
FILE = "file_read"
SYSTEM_DEFAULT = "(system default)"                     # the one fixed entry of the preview's device choice (src/canopy_preview.c)
RECOMPILE = frozenset({"added", "removed", "connected", "disconnected", "setting"})     # the edits after which the engine compiles again


class EngineLink:
    """Keeps one Engine in step with one Editor (see the module's text)."""

    def __init__(self, editor, engine):
        self.editor, self.engine = editor, engine
        self._error = None                                # the sentence this link last put in the message line for a graph that did not compile

    # ---- edits ----

    def edited(self, edit):
        """The editor changed the graph: `edit` is its `Edit`."""
        if edit.kind in RECOMPILE:
            self._recompile(edit)
        elif edit.kind == "knob":
            self._knob(edit)

    def _recompile(self, edit):
        try:
            self.engine.update()
        except (GraphError, BoundaryError) as error:
            self._error = f"not applied: the engine keeps running the previous graph ({error})"
            self.editor.say(self._error, seconds=0)         # (stays until a compile works)
            return
        if self._error is not None:
            if self.editor.message == self._error:
                self.editor.say("")
            self._error = None
        if edit.kind == "removed":
            self.engine.collect()
        if edit.kind == "setting" and edit.detail == "device":
            for node_id in edit.node_ids:
                if self.editor.graph.node(node_id).type == PREVIEW:
                    self._act(node_id, "device")                # a changed setting alone does not reopen the device
        self.refresh_notes()

    def _knob(self, edit):
        node = self.editor.graph.node(edit.node_ids[0])
        try:
            self.engine.set_knob(node.id, edit.detail, node.knobs[edit.detail])
        except GraphError:
            pass                                            # the node is not in the installed graph (that compile failed): the message says so

    # ---- buttons, time, choices ----

    def action(self, node, action):
        """A button of `node` was pressed (not the file node's "open", which the editor handles with its dialog first): the engine does it."""
        self._act(node.id, action)
        self.refresh_notes()

    def _act(self, node_id, action):
        try:
            self.engine.action(node_id, action)
        except GraphError as error:
            self.editor.say(str(error))

    def open_file(self, node):
        """The file node's "open" (the path setting has been set): the engine loads the file now, and the node's message says if it could not."""
        self._act(node.id, "open")
        self.refresh_notes()

    def set_time(self, node, time_ns):
        """The time typed into the time field of a preview node."""
        try:
            self.engine.preview_set_time(node.id, time_ns)
        except GraphError as error:
            self.editor.say(str(error))
            return
        self.poll()

    def choices(self, node, widget):
        """The entries of a choice widget the engine knows better than the descriptor: the preview node's devices ("(system default)" and the names the
        machine has now); None for any other widget."""
        if node.type == PREVIEW and widget.setting == "device":
            return [SYSTEM_DEFAULT] + [name for name in self.engine.audio_devices() if name != SYSTEM_DEFAULT]
        return None

    # ---- what the editor shows ----

    def refresh_notes(self):
        """Asks each node of the installed graph what it says about itself (and each preview node for its warning) and gives the editor the texts."""
        notes = {}
        for node in self.editor.graph.nodes():
            lines = []
            try:
                message = self.engine.node_message(node.id)
                if message:
                    lines.append(message)
                if node.type == PREVIEW:
                    warning = self.engine.preview_warning(node.id)
                    if warning:
                        lines.append(warning)
            except GraphError:
                continue                                    # not in the installed graph (yet)
            if lines:
                notes[node.id] = "\n".join(lines)
        self.editor._set_notes(notes)

    def poll(self):
        """Reads the playback time of every preview node into the editor's time fields; True if any text changed."""
        changed = False
        for node in self.editor.graph.nodes():
            if node.type != PREVIEW:
                continue
            try:
                _playing, time_ns = self.engine.preview_state(node.id)
            except GraphError:
                continue
            changed = self.editor._set_time_text(node.id, format_time(time_ns)) or changed
        return changed
