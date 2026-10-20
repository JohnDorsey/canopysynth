# CANOPY node author guide

How to write a node type: a new kind of node, with its own inlets, outlets, settings and buttons. In version 1 a node type is written **in C** (a plain C
function table behind one registration interface); nodes in numba or Python are planned and the interface is shaped for them, but not built. The exact promises are in
`canopy_design.md` sections 5 to 8 and 12; the headers (`canopysynth/include/canopy.h` and `canopy_node.h`) are the reference and carry the same text as
comments. This guide is the order to read them in.

## 1. The worked example

`examples/example_node.c` is a complete node type, `example.scale` (out = in x gain + offset), and `examples/use_example_node.py` uses it from Python.

From the unzipped folder, in a "x64 Native Tools Command Prompt for VS 2022":

```
cl /nologo /std:c11 /W4 /fp:precise /LD examples\example_node.c /I canopysynth\include /Fe:examples\example_node.dll canopysynth\lib\canopysynth.lib
python examples\use_example_node.py
```

(The folder ships a `examples\example_node.dll` already built, so the second line works at once.) In a source checkout `powershell -File build.ps1` builds it
into `build\examples\`, and `python run_tests.py` runs the Python above against it.

What it shows:

- the **descriptor**: one `CanopyNodeType` filled with plain data (arrays of inlets, outlets and settings) and a table of handlers;
- the two **queries**, both implemented (`scale_at` and `scale_span`);
- how a handler reads its inputs: `canopy_inlet_at` and `canopy_inlet_span`, which answer the connected outlet or the inlet's knob, so the node never asks whether it is connected;
- the **scratch** buffer: `canopy_scratch` (and `scratch_buffers = 1` in the descriptor);
- a **setting** read with `canopy_ctx_float`.

## 2. The descriptor

Fill in a `CanopyNodeType` (zero the structure first, then set what you use). The registry **copies** it, strings and arrays included, so your memory may go
away after the call.

| Field | Meaning |
|---|---|
| `abi_version`, `struct_size` | `CANOPY_ABI_VERSION` and `sizeof(CanopyNodeType)`: a descriptor of another layout version is refused (`CANOPY_ERR_ABI`) |
| `key` | permanent and unique. A node you write must contain a dot: `vendor.name` (segments of lowercase letters, digits and underscores joined by single dots). Keys without a dot are the built-in nodes' |
| `name` | what the editor's menu and the node's title bar show |
| `type_version` | whole number from 1. Raise it when ports or settings change, and register a migration (section 9) |
| `flags` | `CANOPY_FLAG_REALTIME_SAFE`: the handlers allocate nothing, take no locks and call no Python, so the preview's audio thread may run the node. A graph that feeds a preview node with a node that is not flagged gets a warning on the preview (not a refusal). `CANOPY_FLAG_HAS_INTERNAL_RATE`: the node keeps discrete-time state; the registry then adds the setting `internal_sampling_rate` (whole Hz 1 to 384000, default 48000: do not declare it yourself) and the editor shows "Internal sampling rate..." |
| `inlets` | `{key, label, default_knob}`: keys are lowercase letters, digits and underscores; `default_knob` from -1 to 1 |
| `outlets` | `{key, label}` |
| `settings` | `{key, kind, default_int, default_float, default_string, n_choices, choices}`; kind is `CANOPY_SETTING_INT`, `FLOAT`, `STRING`, `PATH` or `CHOICE` (for a choice, `default_int` is the index of the default). Saved with the graph under their keys |
| `widgets` | what the editor shows on the node, as data: `CANOPY_WIDGET_BUTTON` (`label`, `action`: calls `on_action(name)`), `TEXT` and `CHOICE` (`label`, `setting` it edits; a choice may list its `choices`), `LABEL` |
| `scratch_buffers` | the most scratch buffers one call holds at once (a further `canopy_scratch` returns NULL) |
| `handlers` | section 3 |

The order of inlets, outlets and settings is the order of the index arguments of the context calls (`canopy_inlet_at(ctx, 1, ...)` is the second inlet;
`canopy_ctx_float(ctx, 0)` the first setting; the registry's internal-rate setting comes last).

## 3. The handlers

A handler may be NULL if the node does not need it.

| Handler | Runs in | May call |
|---|---|---|
| `query_at(ctx, outlet, t, out)` | the thread that queries | everything below |
| `query_span(ctx, outlet, t0, t1, n, out)` | the thread that queries | everything below |
| `create_shared`, `destroy_shared` | the thread that installs a graph, or collects (never one that queries), with the engine's lock held | the settings getters, `canopy_ctx_shared`, `canopy_ctx_state`; and `canopy_ctx_retire` |
| `create_instance`, `destroy_instance` | the thread that installs, or makes or frees an instance, with the engine's lock held | the settings getters, `canopy_ctx_shared`, `canopy_ctx_state` |
| `on_action(ctx, name)` | the UI thread that calls `Engine.action` (a button was pressed), with the engine's lock held shared | the settings getters, `canopy_ctx_shared`, `canopy_ctx_state`, `canopy_ctx_set_message`, `canopy_ctx_retire`, `canopy_ctx_shared_changed` |

In none of these is a query in progress: `canopy_inlet_at` and `canopy_inlet_span` return `CANOPY_ERR_ARGUMENT` and `canopy_scratch` returns NULL. A slow handler of the first three rows delays
installs and knob writes, never a query.

No handler may call back into the engine (they have no way to: the `ctx` is all you get).

### The two queries

- `query_at(ctx, outlet, t, out)` writes the outlet's value at time `t` (nanoseconds) to `*out` and returns `CANOPY_OK`, or a nonzero status of your own choosing. After a
  nonzero status the engine sets `*out` to 0.0 whatever you wrote.
- `query_span(ctx, outlet, t0, t1, n, out)` fills exactly `n` floats of `out` with the values at the `n` sample times of the span and returns `CANOPY_OK` or a nonzero
  status. After a nonzero status the engine zero-fills `out`. Before calling you, the engine has checked that `n` is in 1 to 65536, that `out` is not NULL and that
  `t1 - t0` fits an int64; you need not.
- Implement one or both. With only `query_at` (a "pointwise" node) the engine builds the span by calling it once per sample time; with only `query_span`, a point
  query is answered by `query_span(t, t, 1)`. Implement both when a span can be done faster than n point queries.
- `out` is the caller's: it may be uninitialised (write before you read), it never overlaps another buffer of the call, and you keep no pointer to it after returning.
- Sample `i` of a span is at `t0 + floor(i * (t1 - t0) / n)` (design section 5). To walk those times yourself use `canopy_sample_time(t0, t1, n, i, &t)`.
- What a point query means between samples is up to the node (the file node interpolates linearly). Ask upstream anything you like at any time, including later times:
  that is how lookahead works.

### Asking upstream

```c
int32_t canopy_inlet_at  (CanopyCtx *ctx, int32_t inlet, int64_t t, float *out);
int32_t canopy_inlet_span(CanopyCtx *ctx, int32_t inlet, int64_t t0, int64_t t1, int64_t n, float *out);
```

Both give the connected outlet's answer, or the inlet's knob position (-1 to 1; time is ignored) when nothing is connected. They return the upstream status unchanged (and a
bad inlet index is `CANOPY_ERR_PORT`). A node that does not care about a failure may ignore the status: after one, a point is 0.0 and a span is zero-filled. Passing the status
on, as the example does, is the normal thing.

`float *canopy_scratch(ctx, n)` gives `n` uninitialised floats (64-byte aligned) from the instance's arena, or NULL when `n` is above 65536, when you already hold
`scratch_buffers` of them, or when the arena is exhausted. They are released when your handler returns; never free them. The arena is sized when the graph is compiled for the deepest chain of
nodes that ask for scratch buffers (256 KB per such node), so in a graph without loops it cannot run out. Do not ask for scratch in the other handlers: it returns NULL there.

### State: three scopes

- **Settings** (saved with the graph): read with `canopy_ctx_int` (also a choice's index), `canopy_ctx_float`, `canopy_ctx_string` (valid until the handler returns). A wrong index or kind gives 0, 0.0 or "".
- **Shared resource**, one per node ID, shared by every instance, surviving edits that keep the node: made by `create_shared`, reached with `canopy_ctx_shared(ctx)`, freed by
  `destroy_shared`. The file node's samples and the preview's audio device are shared resources. It is read by several threads at once: treat it as read-only while queries run,
  or replace it by swapping a pointer (section 6).
- **Instance state**, one per instance (so one per querying thread): `create_instance`, `canopy_ctx_state(ctx)`, `destroy_instance`. Only that thread uses it, so no locks.
  It is carried over to the next graph when an edit keeps the node (same node ID and same type) and destroyed when the node goes.

A create handler that returns NULL means "none": the matching destroy handler is not called, and `canopy_ctx_state` / `canopy_ctx_shared` return NULL. Your queries should
cope (the engine's hidden test filter returns `CANOPY_ERR_MEMORY`).

## 4. Time in C: the public helper functions

Three functions of `canopy.h`, with exact integer arithmetic and no 128-bit integers; they return a status (`CANOPY_ERR_RATE`, `CANOPY_ERR_OVERFLOW`, ...) and leave the outputs
untouched on failure:

- `canopy_ns_to_frame(ns, rate, &frame)`: the nearest frame, `floor((ns * rate + 500_000_000) / 1_000_000_000)`. A host that wants a block at its own rate for `[t0, t1)`
  uses `frame(t1) - frame(t0)` samples, so consecutive blocks tile exactly.
- `canopy_ns_to_frame_fraction(ns, rate, &frame, &fraction)`: the whole frame at or before `ns` and how far (0 <= fraction < 1) it is towards the next: for a node
  that interpolates, `(1 - fraction) * data[frame] + fraction * data[frame + 1]`.
- `canopy_sample_time(t0, t1, n, i, &t)`: the time of sample `i` of a span.

Rates 1 to 9223372036 Hz are accepted. There is no global sample rate: a node that keeps discrete-time state sets `CANOPY_FLAG_HAS_INTERNAL_RATE`, asks upstream on its own
grid (sample `k` at `k / rate` seconds, anchored at t = 0, so the state does not depend on where a query starts), and resamples to what was asked.

## 5. History: nodes that remember (design section 7)

Most nodes need none. A node whose output depends on its past (a filter, an envelope follower) solves it itself, and the usual solution is to **checkpoint** its state every N
seconds and render forward from the nearest checkpoint. Checkpoints are only valid while nothing upstream has changed, and the engine tells you by pulling, not by notification:

```c
uint64_t canopy_ctx_upstream_stamp(CanopyCtx *ctx);
```

returns a digest of the generation numbers of every source upstream of the node: the knobs of unconnected inlets, boundary values, settings and shared resources of the node
and of everything that feeds it. Keep the stamp your checkpoints were made under in your instance state; **at the start of every query read the stamp (before reading any
input) and throw the checkpoints away if it differs.** Reading it first means that an input newer than the stamp only makes a later query discard checkpoints, never keep them wrongly.
`src/canopy_test_nodes.c` (`test_filter`, a hidden one-pole filter) is a complete example, with the internal-rate grid and the checkpoints; its allocation calls are the library's
own (`canopy_alloc`): a node of yours uses `malloc` or its own allocator and is then not `CANOPY_FLAG_REALTIME_SAFE`.

When your shared resource changes in a way that matters downstream (a file was opened), call `canopy_ctx_shared_changed(ctx)` from the handler that changed it: it bumps the
resource's generation number, so every node downstream sees a new stamp.

## 6. Replacing data that queries read

A node that replaces data while other threads may be reading it (a file's samples when Open is pressed again) must not free the old block at once. Publish the new data with a
sequentially consistent atomic pointer swap (queries read it with a sequentially consistent load), then hand the old block to

```c
void canopy_ctx_retire(CanopyCtx *ctx, void *block, void (*release)(void *block));
```

`release` is called when no query that began before the call can still be running: at once if none is, otherwise later by the thread that installs, collects or frees an instance
(or when the engine is freed). Call `canopy_ctx_retire` from `on_action`, `create_shared` or `destroy_shared`, never from a query; `release` must not call back into the engine.
`src/canopy_fileread.c` does exactly this.

## 7. Buttons, widgets and messages

A `CANOPY_WIDGET_BUTTON` with `action = "open"` calls `on_action(ctx, "open")` on the UI thread when pressed (or when a host calls `Engine.action(node_id, "open")`). `on_action`
may use the settings getters and the shared resource and may change both the resource and what the node says: `canopy_ctx_set_message(ctx, "file not found: ...")` shows a line
under the node in the editor and is what `Engine.node_message` returns; an empty text clears it (a node that succeeds clears its message). Do not call it from a query handler (it allocates).

## 8. Using your node type

A host (C or Python) makes a **registry**, adds your type to it, and makes the engine and the graphs over it:

```c
CanopyRegistry *registry = canopy_registry_new();           /* holds the built-in node types */
int32_t status = canopy_registry_register(registry, &type); /* CANOPY_OK, or the first fault: ERR_ABI, ERR_KEY, ERR_DUPLICATE, ERR_DESCRIPTOR, ERR_MEMORY */
/* if not OK, nothing was added and canopy_registry_last_error(registry) says what was wrong */
CanopyEngine *engine = canopy_engine_new(registry);         /* the registry must outlive the engine */
```

From Python (`examples/use_example_node.py`):

```python
types = canopysynth.NodeTypes.from_registry(registry, lib)      # the node types of a C registry, as plain Python data
graph = canopysynth.Graph(types=types)                          # a graph that may name them
engine = canopysynth.Engine(graph, registry=registry)           # you own the registry and free it after engine.close()
editor = canopysynth.Editor(root, graph)                        # its right-click menu lists the types of the graph's catalog, yours after the built-in ones
```

In the editor, a node whose type is not flagged realtime safe is listed as "(not realtime safe)". A saved graph that names your type can be loaded only with a catalog that has it
(a file naming a type that is not installed is refused whole, in version 1). **Version 1 has no mechanism for the stand-alone editor (`run_editor.bat`) to find plug-ins:** it
knows only the built-in types; a host program that registers yours is how they are used.

## 9. Changing a node type later

Raise `type_version` whenever the ports or settings change, and register how a saved node of the older version becomes the next one:

```python
# an illustration: it needs the type to be at version 2 now, with the inlet "input" of version 1 called "in" and the setting "shift" called "offset"
types.add_migration("example.scale", 1, upgrade=lambda settings, knobs: settings.update(offset=settings.pop("shift", 0.0)),
                    inlets={"input": "in"}, outlets={})          # (or canopysynth.register_migration(...) for the built-in catalog)
```

`upgrade(settings, knobs)` changes plain dicts in place (rename a setting, convert a value, add one); `inlets` and `outlets` map old port keys to new ones (None for a port that no longer
exists: its connections are dropped). A file saved under version 1 of a type now at version 3 goes through the migrations 1 and 2 in turn, and what comes out is checked against the current type.

## 10. A checklist

- **Determinism.** The same graph, knobs, boundary values, settings and files must give identical floats every time. Build with `/fp:precise` (MSVC) and without fast-math or
  fused multiply-add contraction; do the arithmetic in a fixed order; do not let thread timing, uninitialised memory or the address of anything into a result. The engine's own tests
  record the output of whole graphs as hashes; a node of yours may do the same.
- **Never write past `out`;** write all `n` floats; never read `out` before you write it; never keep the pointer.
- **Do not clamp** values for the host: the engine does not.
- **Status, not crashes.** A fault is a nonzero return (your own code, or `CANOPY_ERR_MEMORY`), never an exit, an abort or an uncaught signal.
- **Loops.** The engine does nothing about a graph loop (the editor refuses to make one by default): a node that queries its own past through a loop must ask strictly earlier times.
- **Stack.** Each node that asks upstream adds a nested call: keep your frames small, and do not put large arrays on the stack (use `canopy_scratch`).
- **Threads.** Queries of one instance never overlap, queries of different instances do: the shared resource must be safe for concurrent reads, and the instance state needs no lock.
- **Realtime safe** only if it is true: no allocation, no locks, no I/O, no Python in the query handlers.
- **Licence.** CANOPY and its headers are GPL-3.0-or-later (`LICENSE`), and so are `examples/example_node.c` and the other examples: code you copy from them is GPL code. A node
  type that you build against the headers and load into the engine is, in the FSF's view, a combined work with it: distribute it only under terms the GPL allows.
- **Test it.** `tests/c/test_overrun.c` and `tests/c/support.c` in the source repository show how the engine's own tests put canary bytes round the output buffer and ask a node at every
  count and time shape; the same ideas work for yours.
