# SPDX-License-Identifier: GPL-3.0-or-later
"""The stand-alone editor: `python -m canopysynth [graph.json] [--audio system|null]` (what run_editor.bat starts; plan step 14).

A host program of its own and nothing more: a window with the editor in it, a real Engine over the same graph (so the preview node plays and the
file node opens files) and a File menu (New, Open, Save, Save as, Quit) that reads and writes the graph as JSON (`Graph.to_dict`, design section 14).
Programs that embed the editor in their own window use `canopysynth.Editor` and `canopysynth.Engine` directly (docs/user_guide.md)."""
import argparse
import json
import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox

from .engine import Engine
from .errors import BoundaryError, GraphError
from .graph import Graph

FILE_TYPES = [("CANOPY graphs", "*.json"), ("All files", "*.*")]


def read_graph(path):
    """The Graph saved in the JSON file `path`. GraphError (a message that does not name the file: the caller knows it) for a file that is not JSON or
    not a saved graph, OSError for one that cannot be read."""
    with open(path, "r", encoding="utf-8") as handle:
        try:
            data = json.load(handle)
        except ValueError as error:
            raise GraphError(f"it is not a saved graph: it is not JSON ({error})") from None
    return Graph.from_dict(data)


def write_graph(graph, path):
    """Writes the graph as JSON to `path`: into a temporary file next to it first, so that a failed write leaves an old file as it was."""
    text = json.dumps(graph.to_dict(), indent=1)
    temporary = path + ".tmp"
    try:
        with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text + "\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


class App:
    """The window: `App(root, audio="system", path=None)` and then `root.mainloop()`. The four `ask_...` and `show_error` attributes are the dialogs;
    tests replace them."""

    def __init__(self, root, audio="system", path=None):
        self.root = root
        self.audio = audio
        self.graph = self.engine = self.editor = None
        self.path = None
        self.modified = False
        self.ask_open = lambda: filedialog.askopenfilename(parent=root, filetypes=FILE_TYPES)
        self.ask_save = lambda initial: filedialog.asksaveasfilename(parent=root, filetypes=FILE_TYPES, defaultextension=".json", initialfile=initial)
        self.confirm_discard = lambda: messagebox.askyesno("CANOPY", "The graph has changes that are not saved. Discard them?", parent=root)
        self.show_error = lambda text: messagebox.showerror("CANOPY", text, parent=root)
        root.geometry("1000x680")
        menu = tk.Menu(root)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="New", command=self.new, accelerator="Ctrl+N")
        file_menu.add_command(label="Open...", command=self.open, accelerator="Ctrl+O")
        file_menu.add_command(label="Save", command=self.save, accelerator="Ctrl+S")
        file_menu.add_command(label="Save as...", command=self.save_as)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self.quit)
        menu.add_cascade(label="File", menu=file_menu)
        root.configure(menu=menu)
        root.bind("<Control-n>", lambda _event: self.new())
        root.bind("<Control-o>", lambda _event: self.open())
        root.bind("<Control-s>", lambda _event: self.save())
        root.protocol("WM_DELETE_WINDOW", self.quit)
        if path is None:
            self._show(Graph(), None)
        else:
            self._show(read_graph(path), path)

    # ---- the graph on screen ----

    def _show(self, graph, path):
        """Puts `graph` on screen with a new Engine over it. GraphError or BoundaryError (and the old graph stays) if the engine cannot compile it."""
        engine = Engine(graph)
        try:
            engine.set_audio_backend(self.audio)
        except BaseException:
            engine.close()
            raise
        self._release()
        from .editor import Editor
        self.graph, self.engine, self.path, self.modified = graph, engine, path, False
        self.editor = Editor(self.root, graph, width=1000, height=640)
        self.editor.pack(fill="both", expand=True)
        self.editor.add_listener(self._edited)
        self._title()

    def _release(self):
        """Takes the editor and the engine that are on screen away (the engine closes its preview devices)."""
        if self.editor is not None:
            self.editor.destroy()
            self.editor = None
        if self.engine is not None:
            self.engine.close()
            self.engine = None

    def _edited(self, _kind):
        if not self.modified:
            self.modified = True
            self._title()

    def _title(self):
        name = os.path.basename(self.path) if self.path else "untitled"
        self.root.title(f"CANOPY - {name}{' *' if self.modified else ''}")

    def _may_discard(self):
        return not self.modified or self.confirm_discard()

    # ---- the File menu ----

    def new(self):
        if self._may_discard():
            self._show(Graph(), None)

    def open(self, path=None):
        """Opens a saved graph (asks for the file when `path` is None). A file that cannot be read or compiled is reported and the graph on screen stays."""
        if not self._may_discard():
            return
        path = path or self.ask_open()
        if not path:
            return
        try:
            self._show(read_graph(path), os.path.abspath(path))
        except (GraphError, BoundaryError, OSError) as error:
            self.show_error(f"{path} could not be opened: {error}")

    def save(self):
        """Saves to the file the graph came from or was saved to, or asks for one. True if it was saved."""
        return self._save_to(self.path) if self.path else self.save_as()

    def save_as(self):
        path = self.ask_save(os.path.basename(self.path) if self.path else "graph.json")
        return self._save_to(os.path.abspath(path)) if path else False

    def _save_to(self, path):
        try:
            write_graph(self.graph, path)
        except OSError as error:
            self.show_error(f"{path} could not be saved: {error}")
            return False
        self.path, self.modified = path, False
        self._title()
        return True

    def quit(self):
        """Closes the window (after asking, if there are unsaved changes) and the engine."""
        if self._may_discard():
            self._release()
            self.root.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m canopysynth", description="the CANOPY node editor")
    parser.add_argument("graph", nargs="?", help="a saved graph (JSON) to open")
    parser.add_argument("--audio", choices=("system", "null"), default="system", help="the audio system the preview node plays through (default: the machine's own)")
    options = parser.parse_args(argv)
    root = tk.Tk()
    try:
        App(root, options.audio, os.path.abspath(options.graph) if options.graph else None)
    except (GraphError, BoundaryError, OSError) as error:
        root.destroy()
        text = f"{options.graph} could not be opened: {error}"
        if sys.stderr is not None:
            print(text, file=sys.stderr)
        else:                                                       # (started by pythonw, as run_editor.bat does: there is no console to print in)
            messagebox.showerror("CANOPY", text)
        return 1
    root.mainloop()
    return 0
