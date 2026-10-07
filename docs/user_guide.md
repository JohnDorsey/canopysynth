# CANOPY user guide

For people who use CANOPY from a Python program or in its editor. (To write a new kind of node, read `node_author_guide.md`; for the exact promises
of the engine, `canopy_design.md`.) Every Python example below is run by the tests (`tests/python/test_docs.py`), except the few marked `# not run`.

## 1. The idea in five lines

- A **graph** is made of **nodes**. A node has **inlets** (what it reads) and **outlets** (what it can be asked for), and is joined to others by
  **connections**, each from one outlet to one inlet.
- There is no playback and no "current time". An outlet is a function: you ask it for its value at a time, or for `n` samples across a span of time, and
  it answers. Everything upstream is asked in turn.
- Time is a whole number of **nanoseconds** since t = 0 (negative times are fine). There is no sample rate in the graph: the asker chooses how many
  samples it wants.
- Every connection carries one mono stream of `float32`. Several channels need several connections.
- Your program talks to a graph through **boundary nodes**, which have names: it writes a number into a *boundary inlet* and reads from a *boundary
  outlet*.

## 2. Installing

Three ways, all giving the same package (details in `README.md`):

1. **Unzip and run:** `run_editor.bat` starts the editor with nothing installed. Use `python -m canopysynth` from that folder too.
2. **pip:** `pip install canopysynth-1.0.0-py3-none-win_amd64.whl`. This adds the `canopysynth-editor` program. `pip uninstall canopysynth` removes it.
3. **sys.path:** `sys.path.insert(0, r"C:\path\to\folder")`, where the folder is the one that contains `canopysynth\`, then `import canopysynth`.

Requirements: Windows 64-bit; Python 3.9+ (64-bit) with tkinter. Importing `canopysynth` does not load the engine DLL or tkinter; the first `Graph()` or
`Engine()` loads the DLL (and refuses to run if it is not the build this package was made for), and `canopysynth.Editor` imports tkinter when first used.

## 3. The editor

Start it with `run_editor.bat`, `python -m canopysynth [graph.json] [--audio system|null]` or `canopysynth-editor`. The window is the editor panel with a File menu:
New, Open..., Save, Save as... (Ctrl+N, Ctrl+O, Ctrl+S) and Quit. A graph is saved as a JSON file (section 7). A graph that cannot be compiled by the engine (for
example a boundary node without a name, only possible in a file written by another program) is refused with a message. `--audio null` makes the preview play nowhere.

| Do this | To |
|---|---|
| right-click the background | add a node (a list of node types), switch loop protection on or off |
| drag a node | move it |
| drag on the background | select the nodes the rectangle touches; drag any selected node to move them all |
| drag from an outlet to an inlet (or the other way) | connect them. While you drag, the inlets that may take the connection are marked; one that already has a connection, or that would close a loop, is refused with the reason in the message line below the canvas |
| drag a knob up or down; double-click it | turn it; type its value (-1 to 1) |
| right-click a node | Delete; Rename... (a boundary node); Internal sampling rate... (a node that has one) |
| right-click a connected inlet or a connection | delete the connection |
| mouse wheel; Shift+wheel; Alt+wheel; middle-button drag | zoom around the pointer; scroll sideways; scroll up and down; pan |

An inlet with a connection shows no knob; an unconnected inlet shows its knob, and a query through it simply gets the knob's position (-1 to 1) for every
time. A boundary node cannot be given an empty name or a name that another boundary node has. Loops are refused while *loop protection* is on (the default);
it is saved with the graph.

Edits in the window are live: the engine recompiles after every edit and the preview goes on playing. If an edit leaves a graph the engine cannot compile, the message line says so and the engine
keeps running the previous one.

## 4. The built-in nodes

The design document calls them the FileReadNode, the BoundaryInletNode and the BoundaryOutletNode; in code, in saved files and in `Graph.add` they are the type keys below.

| Type key | Inlets (knob default) | Outlets | Settings | Notes |
|---|---|---|---|---|
| `file_read` | none | `left`, `right` | `path` | **Open...** loads a WAV file (PCM 8, 16, 24 or 32 bit, or 32-bit float) into memory. A node whose `path` is already set is loaded when it first reaches a compiled graph; after that the file is read again only when Open is pressed (changing `path` alone does not reload it). A mono file feeds both outlets; more than two channels use the first two. Silence before the start and after the end; between samples, linear interpolation. A file that cannot be read leaves the old sound and the reason is shown under the node |
| `realtime_preview` | `left`, `right`, `center` (0) | none | `device` | **Play**, **Pause**, a time field (hh:mm:ss.mmm, mm:ss or seconds; press Enter) and a device choice. Opens the device at 48000 Hz, sends left+center to the left channel and right+center to the right, clipping. Keeps playing silence after the end. Says under itself if the graph that feeds it has nodes that are not realtime safe |
| `boundary_inlet` | none | `out` | `name` | the host writes a number here by name; every query of `out` answers it, for any time |
| `boundary_outlet` | `in` (0) | none | `name` | the host reads the graph here by name |

That is the whole set for version 1. (Nodes of your own are written in C: `node_author_guide.md`.)

## 5. The Python API

### 5.1 Building a graph

```python
import canopysynth

graph = canopysynth.Graph()                      # loop_protection is on
source = graph.add("boundary_inlet", name="level", x=10, y=20)      # a node: type key, then its settings by key (and its x, y on the canvas)
out = graph.add("boundary_outlet", name="out")
connection = graph.connect(source.outlet("out"), out.inlet("in"))   # returns a Connection(outlet, inlet)
out.set_knob("in", 0.25)                         # the knob of an inlet: -1 to 1; used while nothing is connected to it
source.set("name", "level")                      # change a setting
print(source.id, out.id, graph.nodes()[0].type)  # node IDs: 1, 2, ...; never reused in a graph
print(graph.can_connect(source.outlet("out"), out.inlet("in")))     # the reason a connection would be refused, or None
```

`Graph.add`, `remove`, `connect`, `disconnect`, `can_connect`, `connections`, `connection_into`, `node(id)`, `nodes()`, `boundary_nodes()`, `validate()`,
`has_loop()`, `to_dict()` and `Graph.from_dict(...)` are the graph's calls; the model refuses what is not allowed (`GraphError`) and does not touch the
engine. An outlet may feed any number of inlets; an inlet takes one connection.

### 5.2 Running it: Engine, boundary values, queries

```python
import canopysynth

graph = canopysynth.Graph()
x = graph.add("boundary_inlet", name="x")
y = graph.add("boundary_outlet", name="y")
graph.connect(x.outlet("out"), y.inlet("in"))

with canopysynth.Engine(graph) as engine:        # compiles the graph; close() (or the with block) frees it
    for b in engine.boundary_nodes():            # BoundaryInfo(name, kind, node_id), sorted by name
        print(b.name, b.kind)
    engine.set_boundary("x", 0.7)                # any thread, any float (nothing is clamped)
    with engine.new_instance() as instance:      # one per querying thread, made in that thread
        value = instance.value("y", 0)           # a point query: a float
        block = instance.audio("y", 0, 1_000_000, 8)       # a span query: a memoryview of 8 float32
        print(value, list(block))
```

- `Engine(graph)` compiles the graph as it is. If you change the `Graph` afterwards (through the API: the editor does this itself), call `engine.update()`
  to compile and swap it in. Instances take the new graph up at the start of their next query; a node that is in both versions (same ID, same type)
  keeps its state. If the new graph cannot be compiled, `update` raises and the engine keeps the old one.
- `engine.set_knob(node_id, inlet_key, value)` moves a knob of the compiled graph at once, from any thread, without recompiling. Writing the same knob
  to the `Graph` (`node.set_knob`) is what gets saved; to do both, do both.
- `engine.set_boundary(name, value)`: an atomic store, seen by every query that starts after it.
- `instance.value(name, t_ns)` and `instance.audio(name, t0_ns, t1_ns, n)` ask a boundary outlet. `n` is 1 to 65536. `audio` returns a `memoryview` of `n` float32
  (format `'f'`; `numpy.frombuffer(block, dtype="float32")` wraps it without a copy, if you use numpy; CANOPY does not need it).
  Both may be asked about any times, later ones too (this is how lookahead works).
- `engine.action(node_id, "open")` presses a node's button from code: `"open"` on a `file_read` node (loads the file its `path` names, again),
  `"play"`, `"pause"` and `"device"` on a preview node. `engine.node_message(node_id)` is what the node says about itself (a file error), `""` for nothing.
- `engine.preview_state(node_id)` is `(playing, time_ns)`, `engine.preview_set_time(node_id, t_ns)` moves the playback, `engine.audio_devices()` lists the playback
  devices and `engine.set_audio_backend("null")` makes preview nodes play nowhere (for tests and machines without sound).

### 5.3 Reading a file, in a program

```python
import math, os, struct, tempfile, wave
import canopysynth

with tempfile.TemporaryDirectory() as folder:
    path = os.path.join(folder, "tone.wav")
    with wave.open(path, "wb") as w:             # a half-second 440 Hz tone, 16-bit stereo at 48000 Hz (left channel only)
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(48000)
        w.writeframes(b"".join(struct.pack("<hh", int(16000 * math.sin(2 * math.pi * 440 * k / 48000)), 0) for k in range(24000)))

    graph = canopysynth.Graph()
    song = graph.add("file_read", path=path)     # absolute paths only; relative paths are not supported in version 1 (the file is loaded when the engine compiles)
    left = graph.add("boundary_outlet", name="left")
    graph.connect(song.outlet("left"), left.inlet("in"))
    with canopysynth.Engine(graph) as engine:
        print(repr(engine.node_message(song.id)))        # '' means it loaded; a message says why not (engine.action(song.id, "open") loads it again)
        with engine.new_instance() as instance:
            n = canopysynth.ns_to_frame(10_000_000, 48000) - canopysynth.ns_to_frame(0, 48000)     # 480 frames for the first 10 ms
            audio = instance.audio("left", 0, 10_000_000, n)
            print(n, max(audio))
```

### 5.4 The public helper functions

Times are integers of nanoseconds, so a host must turn them into frames of its own rate. Two functions do it with exact integer arithmetic (the same as
the C ones in `canopy.h`):

```python
import canopysynth

# a block of audio at 48000 Hz for the span [t0, t1): ask for exactly this many samples
t0, t1 = 1_000_000_000, 1_010_000_000
n = canopysynth.ns_to_frame(t1, 48000) - canopysynth.ns_to_frame(t0, 48000)        # 480; consecutive blocks [a, b) and [b, c) tile exactly
# where a time falls between two samples, for interpolation
frame, fraction = canopysynth.ns_to_frame_fraction(251_000_000, 44100)             # (11069, 0.1): 11069.1 frames in
print(n, frame, round(fraction, 3))
```

- **`ns_to_frame(ns, rate)`**: the frame nearest to the time: `floor((ns * rate + 500_000_000) / 1_000_000_000)` (round half up; floor division, so negative times behave
  consistently). Use `ns_to_frame(t1) - ns_to_frame(t0)` for the number of samples of a block, **not** `round((t1 - t0) * rate / 1e9)`: consecutive blocks then
  have no gap and no overlap.
- **`ns_to_frame_fraction(ns, rate)`**: `(frame, fraction)`, the whole frame at or before the time (floor) and how far (0 <= fraction < 1) it is towards the next. A
  node or host that interpolates uses `(1 - fraction) * data[frame] + fraction * data[frame + 1]`.
- Both raise `ValueError` for a time that is not an int64 or a rate outside 1 to 9223372036 Hz, and `OverflowError` when the frame number does not fit in an int64.

### 5.5 Where sample `i` of a span falls

A span query of `n` samples over `[t0, t1)` places sample `i` (0 <= i < n) at `t0 + floor(i * (t1 - t0) / n)`: the last is strictly before `t1`; `t1 < t0` plays the span
backwards; `t1 == t0` puts every sample at `t0`. `n = 0`, `n < 0` or `n > 65536`, and a `t1 - t0` that does not fit in an int64, are errors (`QueryError`).

### 5.6 Saving and loading

```python
import json
import canopysynth

graph = canopysynth.Graph()
graph.add("boundary_inlet", name="a", x=10, y=10)
text = json.dumps(graph.to_dict())               # plain data: store it in your own project file
again = canopysynth.Graph.from_dict(json.loads(text))
print(again.to_dict() == graph.to_dict())        # True
```

The format (design section 14) is a dict with `"format": "canopysynth-graph"`, `"version": 1`, `"loop_protection"`, `"nodes"` (each `{id, type, type_version, x, y,
settings, knobs}`) and `"connections"` (`{from: [node_id, outlet_key], to: [node_id, inlet_key]}`). A file that names a node type that is not installed, or is
not in the format, is refused whole (`GraphError`). A WAV file that no longer exists is not an error when loading: the node is silent, and says why under itself (`engine.node_message`) once an engine has compiled it.
Paths are absolute. A file made by an older node type version is brought up to date by the migrations registered for the type
(`canopysynth.register_migration`, for node authors).

### 5.7 The editor inside your own window

```python
# not run (it opens a window)
import tkinter as tk
import canopysynth

root = tk.Tk()
graph = canopysynth.Graph()
editor = canopysynth.Editor(root, graph)         # a tk.Frame; it edits `graph`
editor.pack(side="right", fill="both", expand=True)
engine = canopysynth.Engine(graph)               # an editor finds the engines made over its graph: it recompiles after each edit,
engine.set_audio_backend("system")               # moves knobs live and sends the buttons of the nodes to them
root.mainloop()
engine.close()
```

`editor.add_listener(function)` is told what the user did (`"added"`, `"connected"`, `"disconnected"`, `"removed"`, `"moved"`, `"knob"`, `"setting"`,
`"loop_protection"`); the virtual event `<<GraphChanged>>` is generated for every edit but moves and knob turns. `canopysynth/app.py` is a small complete
host (a File menu around an editor and an engine) to read as an example.

## 6. Errors

| Exception | When |
|---|---|
| `GraphError` | a graph cannot be built, compiled or loaded: an unknown node type, a bad setting, knob or connection, a file that is not in the format, a node ID or action name of the wrong kind. The message names the node or key. The engine then keeps its previous graph |
| `BoundaryError` | a boundary name that does not exist (or is of the other kind), or a boundary node whose name is empty or used twice (the model allows it while you edit; compiling refuses it) |
| `QueryError` | a query returned a nonzero status; `.status` is the code of `canopy.h`. A point query raises it as a span query does. After a failure the C answer is 0.0 (or zeros); in Python you get the exception |
| `ValueError`, `TypeError`, `OverflowError` | a value that is not what the call takes (a knob outside -1 to 1, a time that is not an int64) |
| `RuntimeError` | an engine or instance that is closed, a closed engine used, or `close()` while instances are open; a DLL that is not the build of this package |
| `MemoryError` | the engine ran out of memory; an install that fails this way leaves the old graph running |

## 7. Rules worth knowing

- **Threads.** One `Instance` per querying thread, made by that thread (`engine.new_instance()`); a node is never used by two threads at once. An instance in
  use by another thread answers `QueryError` (status 14). `set_boundary`, `set_knob` and `engine.action` may be called from any thread. The DLL releases
  Python's GIL during every call, so queries in several threads run in parallel. Close instances (they free their scratch memory) before `engine.close()`.
- **Edits and queries.** An edit takes effect at the next query. A query that is already running is *not* promised a consistent snapshot of an edit made
  at the same moment: a span may mix the old and the new value. While nothing changes, the same query returns the same floats every time.
- **Determinism.** Same graph, knobs, boundary values, settings and files give identical floats every time (the engine is built without fast-math).
- **Loops.** The editor refuses to close a loop. Switching `loop_protection` off is at your own risk: the engine does nothing about a loop whose nodes do not
  ask for strictly earlier times, which can recurse until the host process crashes. The same is true of a chain of about 2500 nodes or more, which
  overflows a 1 MB thread stack (measured: 2500 was fine, 3000 was not); version 1's nodes cannot make chains that deep.
- **Memory.** A file node holds the whole file (as float32) in memory. Each instance holds 256 KB of scratch memory for every node on its deepest chain that
  asks for a scratch buffer. A graph costs about 1.3 kB per node.
- **Not in version 1:** copy and paste, undo, relative paths, placeholders for unknown node types, processing nodes (filters, oscillators, analysis),
  and nodes written in Python or numba.

## 8. Trouble

| Message or symptom | Cause |
|---|---|
| `canopysynth.dll is build N but the Python package is build M` | the DLL and the Python files come from different versions: reinstall or unzip the package again, or run `python run_tests.py` in a source checkout |
| `OSError` ... `canopysynth.dll` while importing `Graph()` | the DLL is missing (a source checkout that was never built) or not 64-bit Windows with 64-bit Python |
| `No module named 'tkinter'` | Python was installed without tcl/tk: run the Python installer again and tick "tcl/tk and IDLE" |
| no sound | `engine.audio_devices()` lists what the machine has; the preview node's Device choice picks one; `engine.set_audio_backend("null")` plays nowhere |
| a node says `file not found...` under itself | the path of a `file_read` node does not exist: press Open... again and choose the file |
