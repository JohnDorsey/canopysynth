# CANOPY - design specification, version 1

Status: version 1 specification, FINAL. No code yet. Started 2026-10-02; finalized 2026-10-02 (round 10).
Every detail here was chosen by the author, or was delegated by the author to the assistant (marked "delegated"). Any change to this design
needs the author's permission.

## 1. What CANOPY is

- Name: CANOPY = "C Audio Nodes in PYthon". The package name and the Python import name are both "canopysynth".
- A standalone Python module (it does not depend on light_bounces) for manipulating and analyzing audio and building simple audio effects by
  linking nodes together with connections.
- Embedded in a Python program that already has a tkinter window; it appears as an interactive panel inside that window, next to the host's
  own controls.
- Its purpose is to be embedded in programs that generate videos, as (1) a source of audio for the video and (2) a source of audio-driven data,
  an alternative to the host's keyframe system. Example: an ellipse's width in light_bounces could be static, keyframed, or linked to a float
  output of CANOPY.
- Minimalist. The audio processing is done in C, fast enough to run in realtime (realtime is used only by one specific node, the realtime
  preview node). The visual node editor is written in Python.

## 2. Non-goals (explicitly excluded)

CANOPY has no animation system, no keyframes, no timeline, no global playback state, no global notion of "the current time", no menu bar, no
file exports, no undo/redo, and (to start with) no copy/paste. It is a tool used inside larger programs.

## 3. Vocabulary

| Term | Meaning |
|---|---|
| node | A unit of the graph with inlets and outlets. Has an integer node ID. |
| inlet | A port on a node that the node reads from. Every inlet has a knob. |
| outlet | A port on a node that can be queried; it answers as a function of the time(s) given in the query. |
| connection | A link from one outlet to one inlet (shown as an arrow in the editor). Always called "connection" in code and docs. |
| knob | The control associated with every inlet (section 6). |
| setting | A saved, non-inlet value of a node: a file path, an audio device, an internal sampling rate (section 12). |
| BoundaryInletNode | A node through which the HOST writes a value into the graph. It has an outlet inside CANOPY. |
| BoundaryOutletNode | A node through which the HOST reads from the graph. It has an inlet inside CANOPY. |
| channel | One mono stream of audio travelling along one connection. |
| compiled graph | The immutable form of a graph that the engine runs (section 8). |
| instance | One thread's engine over a compiled graph; holds that thread's mutable state (section 8). |
| generation number | An atomic counter on each source of change (knob slot, boundary slot, setting, shared resource) (section 7). |
| internal sampling rate | A setting of a node that keeps discrete-time state (section 7). |
| public helper functions | The two nanosecond-to-frame functions of section 4. |
| FileReadNode | The node that reads a .wav file (section 11). |
| realtime preview node | The node that plays audio to a sound device (section 9). |
| timestamp | Time text shown in a user interface (for example the preview node's hh:mm:ss.mmm). Never used inside CANOPY. |

## 4. Time

- Times inside CANOPY are always signed 64-bit integers counting nanoseconds since t = 0.
- Negative times are legal values (the type is signed).
- CANOPY has no global or per-project sample rate.
- The first public helper function converts nanoseconds to a sample-frame index at a given rate, documented once:
  `frame = floor((ns * rate + 500_000_000) / 1_000_000_000)` (round half up; floor division so negative times behave consistently).
- To avoid int64 overflow in `ns * rate`, split first: `sec = ns // 1e9`, `rem = ns % 1e9`,
  `frame = sec * rate + (rem * rate + 500_000_000) // 1e9`. No 128-bit integers (MSVC has none).
- A host that wants a block of N frames at its own rate for [t0, t1) uses `frame(t1) - frame(t0)`, not `round(t1 - t0)`, so
  consecutive requests [a, b) and [b, c) tile exactly.
- The public helper functions accept rates from 1 to 9223372036 Hz (INT64_MAX / 1e9, the largest rate for which the overflow-safe arithmetic
  fits in int64); a rate outside that range, or a frame number that does not fit in int64, is an error (added with the author's permission
  after step 1).
- The second public helper function maps nanoseconds to a whole frame plus a fraction (for interpolating between two samples), computed with the
  same overflow-safe split.
- Both are provided in C for node authors and in Python for hosts. Their documentation calls them "public helper functions" and explains how
  they may be useful (for example: a host computing the sample count `n` for a block at its own rate; a node computing a fractional file
  position to interpolate).

## 5. Queries, connections, audio

- An outlet behaves like a function to whoever queries it. It returns data that is a simple function of the time or timespan given as
  arguments. CANOPY has no playback state and no current time.
- Audio through a connection is mono, float32. Several channels need several connections, one per channel.
- Every connection carries the same single kind of signal: a function of time answered as float32. There are no connection types, so no
  connection can be a type error.
- The node that owns an inlet can query the connected outlet in two ways, and one node may use both kinds at different times:
  1. a point query, in C: `int query_at(Inlet*, int64 t, float* out)`. The caller passes a `float` `out` that it owns; the queried node writes the
     one float32 value for time `t` to it and returns an int status (0 = success). On failure it writes 0.0 and returns a nonzero status
     (changed after step 9, at the author's request: a point query used to return the float itself and could not report an error);
  2. a span query, in C: `int query_span(Inlet*, int64 t0, int64 t1, int64 n, float* out)`. The caller passes the number of samples `n` it
     wants and a buffer `out` that it owns with room for `n` floats; the queried node fills exactly `n` floats, resampling if necessary. It
     returns an int status (0 = success). On failure it zero-fills `out` (all `n` floats when `n` is valid) and returns a nonzero status.
  The two are separate calls; a point query is not defined as a special case of a span query. (Node authors reach them through `ctx`, section 12.)
- Sample placement in a span query: sample `i` (0 <= i < n) is at time `t0 + floor(i * (t1 - t0) / n)`, so the last sample is strictly before
  `t1`. Floor division is mathematical floor (also for negative values). To avoid int64 overflow, compute it with the quotient and remainder of
  `(t1 - t0)` by `n` (`q`, `r`): `t0 + i*q + floor(i*r / n)`.
- Span query errors and edge cases: `t1 < t0` plays the span reversed (the same formula with a negative `t1 - t0`); `t1 == t0` puts all `n`
  samples at `t0`; `n = 0` is an error; `n < 0` is an error; `n` above 65536 is an error; a `t1 - t0` that overflows int64 is an error. A
  missing connection is not an error: the inlet's knob supplies the value (section 6).
- What a point query means between samples is up to the node queried. Example: FileReadNode uses linear interpolation between the two nearest
  samples.
- A node may query any other node with any time arguments at all, including times later than the one it was queried with. This is how lookahead
  works; there is no separate lookahead mechanism.
- Fan-out: an outlet may be connected to any number of inlets. Fan-in: two outlets into one inlet is illegal, and the editor makes it impossible.
- Edits (knob moves, boundary writes, setting changes, graph edits) take effect on the next query; a query that is already running is not
  guaranteed to see a consistent snapshot of them.
- Determinism rule: while the graph is not being changed (same graph, same knob positions, same boundary values, same settings, same files), a
  query with the same arguments returns identical floats every time.
- Ownership of `out` (delegated): the caller owns it and it is exclusively the callee's for the duration of the call; it may be uninitialized
  memory; it never aliases any other buffer given to the same call; the callee must write all `n` floats on success (zero-fill on failure), must
  not read it before writing it, and must not keep the pointer after returning.
- A caller may interpret the floats as audio (not required).
- In Python, a span query on a BoundaryOutletNode returns a memoryview over a float32 array, so a host with numpy can wrap it for free, while
  numpy is not a dependency of CANOPY. A nonzero status raises `QueryError`, for a point query as for a span query.

## 6. Inlets and knobs

- Every inlet has an associated knob.
- A node type may declare a default knob position for each inlet; an inlet with no declared default starts at 0.
- If the inlet has a connection, the knob is grayed out.
- If the inlet has no connection, the knob is interactive, and any query the node makes through that inlet simply returns the knob's float32
  position, between -1 and 1, ignoring `t` (or `t0` and `t1`). A span query on an unconnected inlet returns that value for all `n` samples.
- Each node maps the -1..1 knob position to whatever real unit it needs (Hz, dB...). In version 1 a knob displays its raw -1..1 value;
  displaying real units is postponed until a node needs it.
- A knob's value can be typed by double-clicking it (delegated).

## 7. History, state and generation numbers

- CANOPY has no global rule for how nodes deal with history. Most nodes need none. A node that needs history solves it internally.
- When a new node needs history, ask the author which solution to use. The author usually prefers: checkpoint the node's state every N seconds
  and render forward from the nearest checkpoint. (No checkpoint memory cap in version 1.)
- Staleness is detected by pulling, not by notification. Every source of change (each knob slot, each boundary slot, each node setting and
  shared resource) has an atomic generation number that is bumped when it is written (a knob move, a boundary write, a setting change, a file
  open). The compiled graph records, for each node, which sources lie upstream of it. A node's checkpoints store the generation numbers they
  were made under; at the start of a query the node compares them and discards its checkpoints on any mismatch. Nothing is propagated and no
  registry of instances is needed.
- A node that keeps discrete-time state (a filter, an envelope follower...) has an "internal sampling rate" setting: whole Hz, from 1 to
  384000, default 48000. It asks upstream at that rate, does its processing at that rate, and resamples to the requested `n`, so its results
  do not depend on who asks. The internal sample grid is anchored at t = 0 (sample `k` at `k / rate` seconds), so state does not depend on where
  a query starts. Resampling at the node's edges is linear interpolation (aliasing when decimating is accepted for now). The editor lets the user
  edit that rate by right-clicking the node and choosing "internal sampling rate...".

## 8. Loops, threading, engine and editing

- Feedback loops are allowed in principle, but for now CANOPY has no loop protection of any kind except that the Python editor refuses to let a
  loop be closed. The user can turn that protection off, at their own peril; the setting is saved with the graph. The engine does nothing about
  loops (a loop whose nodes do not query strictly earlier times can recurse without end, which can crash the host process).
- Threading model: a graph is compiled into an immutable compiled graph; every thread that queries (the preview's audio thread, each host worker
  thread) uses its own instance over it, so a node is only ever used by one thread at a time and nothing in the audio path needs a lock. Knob
  positions and boundary values live in one shared table of atomic floats, each slot with its generation number. Live editing during playback is
  done by compile-and-swap: an edit produces a new compiled graph, and each instance adopts it at the start of its next query; the integer node
  ID lets a node's state carry across the swap.
- Node data has three scopes: settings (saved with the graph), shared runtime resources (for example the loaded file samples, the audio device
  handle and the preview node's playback position; one per node ID, shared by all instances, surviving swaps), and instance state (filter state,
  checkpoints; one per instance).
- Each instance has a scratch arena for nodes that need temporary buffers while answering a query (so nothing allocates in the audio thread).
  The largest `n` of one query is 65536. Each node type declares the most scratch buffers it holds at once, and the arena is sized when the graph
  is compiled for the deepest chain of queries.
- The audio device is owned by the C library (no Python in the audio callback), using miniaudio.

## 9. Realtime preview node

- The only place a playback state exists is inside this node. It has a play button, a pause button, and a text field to type a new time, shown
  as hh:mm:ss.mmm.
- It has no outlets. Other nodes cannot see its playback state.
- After the end of the audio (silence) it keeps playing silence until the user pauses.
- It has a control to select the audio device it uses, saved by name; if that device is missing on loading, the system default is used.
- It opens the device at 48000 Hz (miniaudio converts if the hardware differs) and asks the graph in chunks of at most 65536 samples.
- It has three inlets: left, right and center. To the audio device it sends left+center to the left channel and right+center to the right channel,
  clipping a sum that exceeds full scale.
- It warns about graphs containing nodes not flagged `realtime_safe` (section 12); it does not refuse them.

## 10. Boundary nodes (how the host talks to a graph)

- The host addresses a boundary node by name. Boundary node names must be unique. The host can list the boundary nodes by name and kind.
- BoundaryInletNode: the host writes a value to it by name; that value is what any node receives from the BoundaryInletNode's outlet for any
  query, whatever `t` or `t0`/`t1` it uses. It accepts any float. The host's write is an atomic store, visible to any query that starts after it.
- BoundaryOutletNode: the host reads from the graph through it, using the same two query kinds as in section 5.
- CANOPY does not clamp values reaching the host. The host clamps if it needs to; in light_bounces a value is clipped only when it is applied to
  a control that is linked to a CANOPY output.

## 11. Built-in nodes (the whole set for version 1; it is not expanded)

- FileReadNode: reads .wav files only. It has an "open" button to choose a file; the whole file is loaded into memory, and it is reloaded only
  when "open" is pressed again. The path is stored as an absolute path. It knows the file's sample rate and uses it to answer queries given in
  t or in t0/t1/n. It resamples when the requested sample count differs from the file's own density, and answers point queries by linear
  interpolation between the two nearest samples. It returns silence before the file begins and after it ends.
  It has exactly two outlets, `left` and `right`: a mono file feeds the same channel to both; a file with more than two channels uses the first
  two. Accepted formats: PCM at 8, 16, 24 and 32 bits, and 32-bit float, parsed with dr_wav. Anything else is refused at "open".
- Realtime preview node (section 9).
- BoundaryInletNode and BoundaryOutletNode (section 10).
- A hidden, test-only stateful node (not listed in the add-node menu) exists so that the generation numbers and checkpoints are exercised by
  the tests.

## 12. Registration API, extensibility, build and distribution

- The engine and built-in nodes are in C, delivered as a prebuilt DLL loaded from Python with ctypes. The DLL exports a version number that
  the Python code checks on load, refusing to run on a mismatch. WAV files are parsed with dr_wav. Tests run without sound hardware using
  miniaudio's null backend, plus recorded-output tests made possible by the determinism rule. (Delegated.)
- Extensibility is in tiers behind one registration interface: C, then numba, then Python. The node contract does not assume C. The numba tier
  is optional and can wait until a second author exists, but it shapes the registration API from the start. Python and numba nodes are not
  `realtime_safe` and run only in offline rendering.
- A node type is described by one descriptor (a C struct whose first fields are `abi_version` and `struct_size`). Python reads the node type's
  metadata from it. It contains:
  - a permanent key: built-in keys are lowercase letters, digits and underscores (`file_read`); every other key must contain a dot
    (`vendor.name`), so third-party keys cannot collide with built-ins; a display name; an integer type version;
  - flags: `realtime_safe`, `has_internal_rate`;
    when `has_internal_rate` is set, the registry itself adds the node type's setting `internal_sampling_rate` (int, whole Hz 1..384000,
    default 48000; the key is reserved, so a node type may not declare it) and the editor shows the "internal sampling rate..." menu item
    (decided with the author at step 2);
  - inlets (key, label, optional default knob position) and outlets (key, label);
  - settings (key, kind `int`, `float`, `string`, `path` or `choice`, default), saved with the graph;
  - the most scratch buffers the node holds at once;
  - widgets, declared in data: a list of `{kind, label, setting or action, choices}` where kind is `button`, `text`, `choice` or `label`; a widget
    bound to a setting edits it, a widget bound to an action calls `on_action(name)` on the UI thread;
  - handlers: create and destroy the shared resource; create and destroy the instance state; `query_at` and/or `query_span`; `on_action`.
- Handler signatures (C):
  `int query_at(CanopyCtx* ctx, int outlet, int64 t, float* out)` and `int query_span(CanopyCtx* ctx, int outlet, int64 t0, int64 t1, int64 n, float* out)`.
- `CanopyCtx*` is opaque, handed to every handler, valid only until the handler returns, and never used from another thread. It stands for
  "this node, in this instance, during this call". A node never sees engine internals. Through it a node uses:
  - `int canopy_inlet_at(CanopyCtx*, int inlet, int64 t, float* out)` and `int canopy_inlet_span(CanopyCtx*, int inlet, int64 t0, int64 t1, int64 n, float* out)`:
    query the connected outlet, or give the knob value when the inlet is unconnected (so a node never branches on connection); both pass the
    upstream status through (a node that does not care may ignore it: the point's `out` is 0.0 and the span's is zero-filled after a failure);
  - `float* canopy_scratch(CanopyCtx*, int64 n)`: `n` uninitialized floats from the instance's arena, or NULL if `n` exceeds 65536 or the
    arena is exhausted; released automatically when the handler returns; several may be taken in one call, but no more than the node type
    declared in `scratch_buffers` (a further request returns NULL, so that in a graph without loops the arena cannot run out for any other
    node; added with the author's permission at step 3);
  - `canopy_ctx_state(ctx)` and `canopy_ctx_shared(ctx)` (the instance state and the shared resource, as `void*`) and typed getters for the node's
    settings (`canopy_ctx_int`, `canopy_ctx_float`, `canopy_ctx_string`).
- A node type may be "pointwise": it implements only the point query, and the engine derives the span query from it by calling it once per
  sample time given by the sample-placement formula. A node may implement both, for speed.
- In Python (the numba and Python tiers) registration is a decorator, `@canopysynth.node(key=..., inlets=[...], ...)`, and `ctx` is an object with
  the methods `ctx.inlet_at(i, t)`, `ctx.inlet_span(i, t0, t1, n, out)` and `ctx.scratch(n)`, with buffers as memoryviews.
- When a node type changes its settings or ports, it registers a migration from each older type version.

## 13. Editor (Python, tkinter)

- New nodes are added by right-clicking the background and choosing from a list.
- Zoom: the scroll wheel. Horizontal scroll: Shift+scroll wheel. Vertical scroll: Alt+scroll wheel. Pan: middle-click drag.
- Conflicts with tkinter scrollbars are not a concern: the editor will not be used inside a scrollable area.
- The editor makes illegal connections (two outlets to one inlet) impossible, and (by default) connections that would form a loop.
- (Delegated:) nodes are moved by dragging them; a connection is made by dragging from an outlet to an inlet; deleting a node or a connection
  and renaming a boundary node are items on the right-click menu of the node or connection.

## 14. Serialization

- A graph is saved as a dict: `"format": "canopysynth-graph"`, `"version": 1`, `"loop_protection"` (bool), `"nodes"` and `"connections"`.
  - Each node: `{id, type, type_version, x, y, settings, knobs}`; `knobs` maps inlet keys to positions; `x` and `y` are canvas positions;
    `settings` has the node's settings under permanent keys (including the FileReadNode's absolute path, a node's internal sampling rate and
    the preview's device name).
  - Each connection: `{from: [node_id, outlet_key], to: [node_id, inlet_key]}`.
- Permanent string keys are used for node types, inlets, outlets and settings. Node IDs are never reused within a graph.
- Loading a graph that names a node type that is not installed rejects the whole file (version 1).
- Loading a graph whose WAV file no longer exists is not an error: the node is silent and flagged.
- Relative paths are not supported in version 1.

## 15. Python API (version 1)

```python
import tkinter as tk
import canopysynth

root = tk.Tk()
graph = canopysynth.Graph()
song  = graph.add("file_read", path="C:/audio/song.wav")
left  = graph.add("boundary_outlet", name="song_left")
level = graph.add("boundary_inlet",  name="intensity")
graph.connect(song.outlet("left"), left.inlet("in"))
graph.loop_protection = True                       # saved with the graph
# or: graph = canopysynth.Graph.from_dict(d, base_dir=None)   (base_dir is accepted but unused in version 1)

editor = canopysynth.Editor(root, graph)           # a tk.Frame
editor.pack(side="right", fill="both", expand=True)

engine = canopysynth.Engine(graph)                 # keeps the latest compiled graph; editor edits trigger compile-and-swap
for b in engine.boundary_nodes():                  # BoundaryInfo(name, kind, node_id)
    print(b.name, b.kind)
engine.set_boundary("intensity", 0.7)              # any thread

inst = engine.new_instance()                       # one per querying thread, created in that thread
value = inst.value("song_left", t_ns)              # point query -> float
audio = inst.audio("song_left", t0_ns, t1_ns, n)   # span query -> memoryview of n float32; QueryError on a nonzero status

n = canopysynth.ns_to_frame(t1_ns, 48000) - canopysynth.ns_to_frame(t0_ns, 48000)
frame, frac = canopysynth.ns_to_frame_fraction(t_ns, 44100)

d = graph.to_dict()                                # the host stores this in its own project file
```

Exceptions: `QueryError` (a query returned a nonzero status), `GraphError` (a graph cannot be compiled or loaded) and `BoundaryError` (a problem with
a boundary node or its name: a name that does not exist, or a boundary node whose name is empty or repeated). The two are separate classes
(changed at step 9, at the author's request: the design had put boundary names under `GraphError`).

## 16. Errors

- A missing or unreadable WAV when pressing "open": the node keeps its old file (or silence if none) and shows the message on the node.
- Asking the engine for a boundary name that does not exist raises `BoundaryError`, naming the boundary.
- A graph that cannot be compiled (an unknown node type, a bad setting or connection) raises `GraphError` with the reason, and one whose boundary
  nodes have an empty or repeated name (possible when built through the Python API) raises `BoundaryError`; the editor shows either and keeps the
  previous compiled graph running.
- A C query, point or span, reports errors with its int status (section 5): after a failure a point's float is 0.0 and a span is zero-filled. In
  Python every nonzero status raises `QueryError` (and a boundary name that does not exist raises `BoundaryError`).

## 17. Not in version 1

Not in version 1: copy/paste, undo/redo, relative paths, placeholders for unknown node types, a checkpoint memory cap, displaying knob values in
real units, processing nodes (filters, oscillators, analysis...), and the numba/Python node tiers with the Python registration decorator (the
API is shaped for them, but every version 1 node is a C node; decided with the author at step 2).
