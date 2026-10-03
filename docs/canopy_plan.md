# CANOPY - build plan for version 1

Created 2026-10-02. Status: **in progress** (steps 0 to 6 done).
The design is `docs/canopy_design.md` (read it before every step). This plan builds exactly that design and nothing else.
The project folder is `C:\Users\Argh\Documents\ai\projects\canopysynth`; the design and this plan live in its `docs\` folder.

## Rules (each applies to every step)

- R1 The design is law. Build only features that are in `canopy_design.md`. A change, an addition, or a choice the design does not make needs the
  author's permission FIRST: stop and ask, with a recommendation and its trade-offs. Implementation choices the design leaves open (listed under
  "Questions still to ask" below) are asked at the step where they first matter, not guessed.
- R2 Tests first for anything with a precise contract (time maths, span placement, error statuses, determinism, serialization): write the test
  (with an independent reference where possible, for example Python big integers for the int64 maths), see it fail, then implement.
- R3 After every edit: compile (C and Python), then run the FULL test suite (C tests and Python tests), not just related tests. A step ends only
  when everything is green and the real-window or real-device checks that the step lists have been run.
- R4 Say plainly what was VERIFIED (ran it) and what is BELIEVED (read it, reasoned about it). Measure claims about speed and about threading with
  a throwaway script rather than reasoning from the code.
- R5 No hidden design drift: every statement in the design maps to a test or a check (see "Design coverage" below); the final steps audit this.
- R6 Reporting rule: end every step's summary with what was done, what the next step is, and a reminder of the effort level to set before the
  author says "continue". Update this file's progress log in every step.
- R7 Windows is the platform (MSVC; no 128-bit integers). New source files use CRLF line endings.
- R8 Floating point must be deterministic (the determinism rule of design section 5): no fast-math, no flags that change results between runs.
- R9 Dependencies stay minimal: Python standard library + tkinter; no numpy dependency; C side: miniaudio and dr_wav (vendored single headers).
- R10 Never delete the author's files; scratch work goes in the session scratch folder.

## Decisions recorded at step 0 (implementation choices the design leaves open; asked and answered 2026-10-02)

- Build: `build.ps1` calling MSVC `cl` (found with vswhere), C11, `/O2 /W4 /WX /fp:precise`. clang is not used for now.
- Platform: Windows 64-bit only for version 1 (other operating systems later; keep the code portable where that costs nothing). Python 3.9 or
  newer, tested on 3.11 (the author chose Windows-only after the trade-offs were explained; the Python minimum was not separately confirmed).
- Layout: `docs/`, `src/`, `third_party/`, `canopysynth/` (Python package + built DLL), `tests/c/`, `tests/python/`, `build/`, `build.ps1`, `run_tests.py`.
- Tests: one command, `python run_tests.py` (builds, runs the C tests and the Python tests, prints one total).
- Delivery counter: `CANOPYSYNTH_BUILD`, as in light_bounces (+1 per finished prompt that changed code), in `src/canopy.h` and `canopysynth/version.py`.
- Version control: none for now.
- Vendoring miniaudio.h and dr_wav.h moves from step 0 to the steps that first need them (dr_wav at step 6, miniaudio at step 7); each download
  needs the author's explicit permission (filename, source, size), and their licenses are recorded then.

## Decisions recorded at step 3 (asked and answered 2026-10-02)

- A point query on a node that implements only `query_span` is answered by the engine with a one-sample span query, `query_span(t, t, 1)`
  (0.0 if the status is nonzero). (Recorded here, not in the design: the author's permission to edit the design covered only the scratch rule.)
- The typed settings getters read by setting INDEX: `canopy_ctx_int(ctx, index)`, `canopy_ctx_float(ctx, index)`, `canopy_ctx_string(ctx, index)`;
  the index is the setting's position in the descriptor (the engine's internal-rate setting comes last). A CHOICE reads as its chosen index through
  `canopy_ctx_int`; a wrong kind or a bad index returns 0, 0.0 or "".
- `canopy_scratch` returns NULL when the node asks for more buffers in one call than its descriptor declares in `scratch_buffers` (added to design
  section 12 with the author's permission). Also NULL for `n < 1` (my choice, not in the design: a request for no floats is a bug in the node).
- Choices of mine that the design leaves open (the author may veto any of them):
  1. Node IDs are int64. A graph is described with `canopy_graph_*` calls that only record data; everything is checked when it is compiled.
     Ports are named by key in a graph and addressed by index at run time (the order of the descriptor).
  2. The engine object (`canopy_engine_*`) owns what must outlive one compiled graph: the knob slots and the shared resources, kept per node ID
     and node type. A node ID that comes back with another type gets slots and resources of its own. A graph description's knob position replaces
     the slot's current value (and counts as a write only if it differs); host writes between installs are therefore overwritten by the next
     install, which is right when the host keeps its graph model in step with the knobs.
  3. Every span request is checked the same way whether or not the inlet is connected (n, then `out` != NULL, then overflow of t1 - t0), so a
     node that works with an unconnected inlet cannot start failing once something is connected to it. On any failure the engine itself zero-fills
     `out` (all n floats when n is valid), also when the node scribbled in it before returning a status; a node's own nonzero status is passed on.
  4. An instance refuses a second concurrent use, and a call from inside one of its own handlers, with `CANOPY_ERR_BUSY` (point queries answer
     0.0), because the GIL is released during ctypes calls and two Python threads sharing an instance would otherwise corrupt its scratch arena.
  5. Outside a query (create/destroy handlers, `on_action`) the context calls are harmless: `canopy_inlet_at` gives 0.0, `canopy_inlet_span`
     `CANOPY_ERR_ARGUMENT` (zero-filled), `canopy_scratch` NULL; the settings getters and `canopy_ctx_shared` work.
  6. A scratch request that fails does not use up the node's declared count. The arena of a graph with a loop anywhere is sized for every node
     holding its buffers at once (the sum of the declared counts), and a descriptor that declares absurdly many buffers is refused at compile time.
  7. C11 atomics are used from step 3 (the knob slots), not step 4; `build.ps1` passes `/experimental:c11atomics` and `_CRT_SECURE_NO_WARNINGS`.
  8. The memory check is a second run of all C tests against the MSVC debug heap (`run_c_tests_debug.exe`), because AddressSanitizer is not usable:
     this Visual Studio has no x64 ASan runtime and no `libvcasan.lib` (installing the "C++ AddressSanitizer" component might enable it).
     (Superseded at step 4: the author installed the component and the C tests now also run a third time under AddressSanitizer.)
  9. Library allocations all go through `canopy_alloc`/`canopy_realloc`/`canopy_free`/`CanopyPool` so that tests can count live blocks and fail
     the Nth allocation; `canopy_alloc_live`, `canopy_alloc_total` and `canopy_instance_arena_floats` are exported as diagnostics.

## Decisions recorded at step 4 (asked and answered 2026-10-02)

Answered by the author:
- Adoption of a newly installed graph, without allocating in the audio thread: **prepared by the editing thread.** Installing a graph builds, for
  every live instance, a package (the table of states the instance will have, fresh state for the nodes that are new, a bigger arena if the new
  graph needs one); the instance applies the packages in order at the start of its next host query by swapping pointers (no allocation, no free, no
  lock); the editing thread frees what the instance has finished with (the old table, the old arena, the state of nodes that are gone, through
  `destroy_instance`) at a later install, `canopy_instance_free` or `canopy_engine_collect`. So `create_instance` and `destroy_instance` run in the
  editing (or host) thread, never in the thread that queries.
- The hidden test-only node is **not in the normal registry**: it is registered only by the exported `canopy_registry_add_test_nodes(registry)`
  (flat key `test_filter`), so no registry made by `canopy_registry_new` can list it.
- The author installed the "C++ AddressSanitizer" component: the C tests now run a third time under `/fsanitize=address`.
- Zero-filling `out` on a failed span query stays unconditional (not a setting).
- `canopy_engine_set_knob` / `canopy_engine_get_knob` are exported C functions (the editor reaches them through ctypes) but are not part of the
  design's host API; no public Python `set_knob` is added at step 9 unless the author asks.

Choices of mine that the design leaves open (the author may veto any of them):
1. **The stamp is a digest, not a list.** The design says a node's checkpoints store the generation numbers they were made under and compare them
   at the start of a query. A node cannot hold a variable number of counters conveniently, so `canopy_ctx_upstream_stamp(ctx)` returns ONE 64-bit
   value that mixes the generation numbers of every source upstream of the node (read now, with acquire loads) into a digest made at compile time
   of the things that do not change: the identity of every node in the cone (record uid, ID, type key), its wiring (which outlet feeds which
   inlet) and its settings' generation numbers. A node keeps the stamp with its checkpoints and discards them when the stamp it reads at the start
   of a query differs. Any change of any one counter changes the stamp (the mixing steps are bijections); two different states give the same stamp
   only by a 64-bit collision (about 2^-64 per comparison: believed negligible, not provable). A node must read the stamp BEFORE it reads any input.
2. **Sources of a node** (the "upstream" of the design, the node itself included, loops included): the knob slot of each unconnected inlet (the
   knob of a connected inlet is not read by anything, so moving it is not a change), the node's own shared resource (bumped by the new
   `canopy_ctx_shared_changed(ctx)`, which a node calls after it replaces its data, for example when "open" is pressed again), a boundary slot, and
   every setting. Rewiring changes the stamp even when no counter does (the wiring is in the digest).
3. **Settings' generation numbers** are kept per node record and go up at an install when the new value differs from the installed graph's (floats
   bit for bit, so +0.0 and -0.0 differ; strings by content; integers and choices by value). A value that goes back gets a new number again: the
   numbers only increase.
4. **Records.** What survives installing another graph is kept per node ID and node type in a heap-allocated record (knob slots, boundary slot, shared
   resource and its generation number, the settings' numbers, a `uid` that is never reused). A record is destroyed (`destroy_shared`) when the last
   compiled graph that holds it is freed; the `uid` is in the digest, so a node that is removed and later added again, after its record was
   destroyed, gets a new stamp even if every counter happens to match.
5. **The boundary slot** is a built-in-only type flag, `CANOPY_FLAG_BOUNDARY_SLOT` (value 4, in the internal header; the registry refuses it for
   any type not registered with `canopy_registry_register_builtin`). The host writes it with the internal `canopy_engine_set_boundary_value` (any
   float, NaN and infinities included, nothing clamped; not exported yet: step 5 exports the by-name versions), the node reads it with
   `canopy_ctx_boundary_value(ctx)`; it starts at 0.0.
6. **An engine lock.** The engine keeps the list of live instances (the packages need it), records and compiled graphs under one SRW lock
   (`CanopyLock`, Windows only like the rest of version 1). Taken exclusively by installing, `canopy_engine_new_instance`, `canopy_instance_free`,
   `canopy_engine_collect` and `canopy_engine_free`; shared by `set_knob`, `get_knob`, `set_boundary_value`, `action`, `node_count` and
   `graph_serial`. A query never takes it. `canopy_engine_free` still refuses (`CANOPY_ERR_BUSY`) while instances exist.
7. **Installing is a transaction.** Everything that can fail for lack of memory (records and shared resources of new nodes, setting numbers, the
   lists of sources, a package for every instance) is done before anything an instance can see is touched; if any of it fails all of it is undone
   and the engine is exactly as it was (`CANOPY_ERR_MEMORY`, message "out of memory"). A test fails the Nth allocation for every N.
8. **Reclaiming.** An older compiled graph is freed when no instance can still use it (the oldest graph any instance has not left yet, applied or
   not), at each install, `canopy_instance_free` and `canopy_engine_collect` (which returns the number of graphs still held: 1 when every
   instance has adopted the newest). A node that has left the graph therefore keeps its shared resource until then.
9. **Additions to the C API the design does not name** (all small): `canopy_engine_collect`, `canopy_engine_graph_serial`,
   `canopy_instance_graph_serial` (diagnostics and management), `canopy_ctx_upstream_stamp`, `canopy_ctx_shared_changed`,
   `canopy_registry_add_test_nodes`. Internal and not exported (declared in `canopy_internal.h`, used by built-in nodes and the C tests):
   `canopy_frame_to_ns` (the time of a frame of a grid, rounded half up), `canopy_ctx_boundary_value`, `canopy_engine_set_boundary_value`; step 5
   adds the by-name boundary calls a host uses.
10. **The hidden filter `test_filter`** (documented at the top of `src/canopy_test_nodes.c`): a one-pole low-pass `y[k] = y[k-1] + a * (x[k] -
    y[k-1])`, `a` = clamp((coef + 1) / 2, 0, 1), in float32 one operation at a time, on the grid sample k at k / rate seconds (anchored at 0, the time
    rounded half up to the nanosecond), `initial` before the first sample, linear interpolation between the two neighbouring samples with the position
    between them exact. Settings: `initial` (FLOAT), `checkpoint_seconds` (INT, 10; below 1 counts as 1, limited to 3,600,000) and the
    `internal_sampling_rate` the registry adds. A checkpoint holds the state just before sample j * M; a query renders forward from the nearest
    checkpoint or from where the previous query stopped, and a stamp that differs from the one the checkpoints were made under throws them away.
    It allocates while querying, so it is not `realtime_safe`.
11. **Where the handlers run.** `create_shared`, `destroy_shared`, `create_instance` and `destroy_instance` run in the thread that installs, collects,
    makes or frees an instance, with the engine's lock held exclusively; `on_action` runs in the caller's thread with the lock held shared. A slow
    one therefore delays installs, and knob writes while an install runs or waits (measured: on an SRW lock held shared, a waiting exclusive request
    makes a later shared request wait, 20 rounds out of 20), never a query; none of them may call back into the engine.
12. **Idle instances keep old graphs.** An instance that does not query keeps every graph installed since its last query, and a package for each
    (measured below: 0.7 KB per install for a chain of 10 nodes, 114 KB for 100, 8.7 MB for 1000). A host should query its instances regularly or
    free and make again one that will sit idle for long. I considered letting the installing thread bring an idle instance up to date by taking
    its busy flag, and did not: a query arriving at that moment would be refused with `CANOPY_ERR_BUSY`, an audible dropout in the audio thread,
    and it changes when adoption happens. Revisit at step 12 if the editor's use of instances makes it matter.
13. **A chain of N nodes costs N squared at install.** The design asks the compiled graph to record, for each node, the sources upstream of it; for
    a chain that is about N^2/2 entries (measured below). Real graphs have tens of nodes. If graphs ever get large a bitset per node would cut the
    memory about twentyfold; not done.

## Decisions recorded at step 5 (asked and answered 2026-10-02)

Answered by the author:
- The C host calls are **by name only** (no separate resolve call): `canopy_engine_set_boundary`, `canopy_engine_boundary_count`,
  `canopy_engine_boundary_at`, `canopy_instance_read_at`, `canopy_instance_read_span`.
- A boundary name is **any non-empty text, unique** across both kinds, case-sensitive, compared byte for byte.

Choices of mine that the design leaves open (the author may veto any of them):
1. `canopy_engine_boundary_at` copies the name out (buffer, capacity, full length returned) instead of returning a struct with a pointer: a pointer
   into the compiled graph would dangle after the next install. The listing is sorted by name in byte order (capitals first); count and `at` are two
   calls, so an install between them can make `at` return `CANOPY_ERR_INDEX`.
2. A name that is unknown, or of the wrong kind (writing an outlet, reading an inlet), is `CANOPY_ERR_NODE` (a point read gives 0.0); a NULL name is
   `CANOPY_ERR_ARGUMENT`. No new status code.
3. A boundary value belongs to the node (its record), not to its name: renaming a node keeps the value; a node that leaves the graph and later comes
   back (after the engine let go of the old graphs) starts at 0.0 again. A graph description does not carry boundary values.
4. A reader finds its outlet by name in the graph the instance runs (after adopting a newly installed one), so a read never uses a name from a graph
   the instance has not reached.
5. `canopy_registry_new()` now returns a registry with the boundary types in it (and NULL if registering them runs out of memory); the type flag
   `CANOPY_FLAG_BOUNDARY_NODE` (16) is built-in only like the slot flag.

## Decisions recorded at step 6 (asked and answered 2026-10-03)

Answered by the author:
- **dr_wav.h may be downloaded** (done: 369,705 bytes from the dr_libs master, public domain / MIT-0; provenance in `third_party/README.md`).
- **Replaced samples are retired and freed when no query can see them** (epoch per instance, two atomic increments per host query, no locks).
- **A generic node message**: `canopy_ctx_set_message` / `canopy_engine_node_message`, which later nodes (the preview's device errors) reuse.
- **The file is read at creation and on "open"**: when the node first appears in an installed graph, and whenever the action "open" is pressed (using
  the path of the installed graph); installing a graph with another path does not reload.

Choices of mine that the design leaves open (the author may veto any of them):
1. **Time**: frame k of the file is at k / (sample rate) seconds, the file starting at t = 0; the file covers t = 0 to the time of its last frame and
   everything outside is silence (no ramp to zero at the edges). A point between frames is the linear interpolation with the position between them
   exact. A span is the point query at each sample time (so resampling is linear interpolation both ways; decimating aliases, as the design accepts).
2. **Integer samples** are converted by dr_wav: 16, 24 and 32 bits divide by 2^15, 2^23 and 2^31; 8-bit PCM (unsigned in WAV) maps 0..255 to -1..1
   (255 is +1, 128 is a little above 0), dr_wav's own rule.
3. **Messages**: "file not found: path", "not a file: path", "not a WAV file, or damaged: path", "format not supported (...); accepted: ...", "the
   path must be absolute...", "no file chosen" (open with an empty path), "out of memory loading path". At most 255 bytes. A node that succeeds clears
   its message. A graph loaded with a missing file is silent and flagged (message set at creation), as design section 14 asks.
4. **A file shorter than its header says** is used as far as it goes; a file of zero frames is silence with no message; a sample rate outside
   1 .. 9,223,372,036 Hz (`CANOPY_MAX_HELPER_RATE`) is refused; a header that claims more data than the file holds is clamped by dr_wav.
5. **Paths** are UTF-8 text converted to wide characters (so non-ASCII names work); "absolute" means a drive letter or a UNC prefix.
6. **Retiring is for any node**, not only this one (`canopy_ctx_retire` in `canopy_node.h`), so later nodes that swap data (the preview's buffers)
   use the same mechanism. Cost: two sequentially consistent increments per host query. If retiring runs out of memory for its note, it waits for the
   running queries itself (the editing thread spins) instead of leaking or freeing early.

## Questions still to ask, and where

(Answered at step 2: atomics = C11 stdatomic; no Python tier in version 1. Answered at step 4: how an instance adopts a new graph.)

| Question | Step |
|---|---|
| Package distribution format for the prebuilt DLL (wheel, a plain folder...) | 14 |
| How the preview node's run-time list of audio devices is supplied to a CHOICE widget | 7 |

## Steps (one prompt each, unless stated; the effort level is what to set BEFORE telling me to continue)

### Step 0 - decisions and skeleton. Recommended effort: MEDIUM - DONE (build 1)
- [x] Asked and recorded the decisions above.
- [x] Layout created; docs moved into `docs/`; `build.ps1`; `run_tests.py`; a `CLAUDE.md` for the folder. (Vendoring moved to steps 6 and 7.)
- [x] One C test and one Python test through `python run_tests.py`: the DLL builds with MSVC, loads through ctypes, and its build number matches the C
      header and the Python package. Mutation-checked: changing the Python number to 2 makes the Python test fail.
- Done: "2 passed, 0 failed, 2 total".

### Step 1 - the public helper functions. Recommended effort: HIGH - DONE (build 2)
- [x] Tests first (design section 4): `ns -> frame`, the overflow-safe split near the int64 limits, block tiling, `ns -> (frame, fraction)`, each
      checked against Python big-integer references over about 40,000 edge and random cases; C vector tests in `tests/c/test_time.c`.
- [x] Implemented in C (`src/canopy_time.c`, declared in `src/canopy.h`) and in Python (`canopysynth/helpers.py`: `ns_to_frame`,
      `ns_to_frame_fraction`; docstrings call them "public helper functions" and explain their use; the Python versions raise `ValueError` /
      `OverflowError` for the same conditions the C ones report). `canopy_sample_time` (span-query sample placement) is C-only, as the design
      lists only the two frame helpers as Python helpers.
- [x] First status codes in `canopy.h` (`CANOPY_OK`, `_ERR_RATE`, `_ERR_OVERFLOW`, `_ERR_N`, `_ERR_INDEX`); step 2 adds the rest. `CANOPY_MAX_N` = 65536.
- Derived, not chosen: the helpers accept rates 1 .. 9223372036 (INT64_MAX / 1e9), the largest for which the intermediate products fit in int64;
  a result that does not fit returns `CANOPY_ERR_OVERFLOW` (the design only says overflow-safe).
- Found by the big-integer comparison: the first C version reported a false overflow for `ns = INT64_MIN` at 1e9 Hz (the product `sec * rate`
  is below INT64_MIN although the frame is exactly INT64_MIN). Fixed by adding the two terms in a rearranged order; pinned by a regression test.
- Mutation-checked: removing the half-up rounding, or either floor correction, makes 3-6 tests fail.
- Done: 20 passed, 0 failed.

### Step 2 - node-type descriptor, registry, status codes. Recommended effort: HIGH - DONE (build 3)
- [x] Asked and decided: atomics use C11 `<stdatomic.h>` (needs `/experimental:c11atomics`; used from step 4); the Python-tier registration decorator
      and Python/numba nodes are NOT in version 1 (design section 17 updated); the registry adds the `internal_sampling_rate` setting itself when a
      node type sets `has_internal_rate` (design section 12 updated).
- [x] `src/canopy_node.h`: the descriptor (`abi_version`, `struct_size`, key, name, type version, flags, inlets with default knobs, outlets, settings
      of five kinds, widgets in data, scratch count, handlers) and the registry API; `src/canopy_registry.c`: validation, deep copy, lookup in
      registration order, `canopy_registry_last_error`. Built-in keys are plain, every other key needs a dot (an internal `register_builtin` for
      the DLL's own types). Descriptors from a newer layout of the same version (larger `struct_size`) are accepted.
- [x] Status codes for descriptor errors added to `canopy.h` (`ABI`, `KEY`, `DUPLICATE`, `DESCRIPTOR`, `MEMORY`) with `canopy_status_message`;
      the query errors of design section 5 were already there (`N`, `INDEX`, `OVERFLOW`).
- [x] Python: `canopysynth/_descriptor.py` (ctypes mirror + `read_node_type`), `canopysynth/_lib.py` (`load_dll`, `check_versions`: RuntimeError on a
      build or layout-version mismatch). Descriptor sizes are pinned on both sides (160/56/48/56 bytes on x64).
- [x] Mutation-checked: 12 deliberate faults in the registry and 2 in the version check are all caught. (The first round showed the setting-fault
      tests were passing for the wrong reason - their widgets named settings the test had removed; fixed.)
- Notes for later steps: (1) the migration hook for node-type versions belongs to serialization, which is Python: it is built at step 8, not here;
  (2) a CHOICE widget has a static list of choices, but the preview node's audio devices are only known at run time: at step 7 I must ask how the
  device list is supplied (a design question); (3) `CanopyCtx` is declared but its calls (`canopy_inlet_at`...) arrive at step 3.
- Done: 37 passed, 0 failed.

### Step 3 - compiled graph, instances, queries. Recommended effort: MAX - DONE (build 4)
- [x] Asked and decided (see "Decisions recorded at step 3"): the point query of a node that has only `query_span`, settings read by index, and the
      declared-count rule of `canopy_scratch` (design section 12 updated for that last one, with the author's permission).
- [x] Graph description and compile: `src/canopy_graph.c` (`canopy_graph_*`, records data only) and `canopy_engine_set_graph` in `src/canopy_engine.c`
      compile it into an immutable compiled graph (nodes sorted by int64 ID, types resolved, settings and knobs at their defaults or as described,
      connections resolved, arena sized) and install it. Faults are `CANOPY_ERR_GRAPH` with a message that names the node or key: duplicate node ID,
      unknown node type, a setting, knob or connection naming something that does not exist, a setting set with a call of the wrong kind, a CHOICE
      index out of range, a non-finite FLOAT, an internal rate outside 1..384000, a knob outside -1..1, two connections into one inlet. On a fault
      nothing changes. Loops are not a fault. (The "duplicate boundary names" fault moves to step 5, with the boundary node types.)
- [x] `CanopyEngine` (`canopy_engine_new/free/set_graph/last_error/node_count/set_knob/get_knob/action`) owns what outlives one compiled graph, per node
      ID and node type: the knob slots (C11 atomic float bits plus a generation number bumped after every write, value stored first), the shared
      resource (`create_shared`, destroyed with the engine) and every compiled graph (kept until the engine is freed). Installing another graph keeps
      the slots and resources of nodes with the same ID and type. `canopy_engine_action` calls `on_action`.
- [x] `CanopyInstance` (`canopy_engine_new_instance`, `canopy_instance_free`): its own state per node (`create_instance`) and its own scratch arena.
      The host reads through an inlet (`canopy_instance_inlet_at/span`: what a BoundaryOutletNode will do). One caller at a time (`CANOPY_ERR_BUSY`);
      the engine cannot be freed while an instance exists. An instance keeps running on the graph it was made with (adopting a newer one is step 4).
- [x] Queries (`src/canopy_instance.c`): point and span dispatch; knob fallback for unconnected inlets (point and span); a pointwise node's span is one
      point call per sample time (placement from `canopy_span_plan`, the same code `canopy_sample_time` now uses); a span-only node answers a point
      query with a one-sample span; the checks of every span request are the same whether or not the inlet is connected; `out` is zero-filled on any
      failure. Context calls: `canopy_inlet_at/span`, `canopy_scratch`, `canopy_ctx_state/shared`, `canopy_ctx_int/float/string`.
- [x] Scratch arena: the heaviest chain of declared `scratch_buffers` times 65536 floats (the sum over all nodes if there is a loop); `canopy_scratch`
      gives 64-byte aligned buffers, NULL for n < 1 or > 65536, beyond the declared count, or when the arena is used up; released when the handler returns.
- [x] Tests: `tests/c/test_alloc.c` (counted allocation, failure hook, pool, span plan), `test_graph.c` (settings and typed getters, every compile fault
      from a table, install semantics, knobs, lifecycle of shared resources and instance state, actions, NULL arguments, and a sweep that makes the Nth
      allocation fail for every N), `test_query.c` (knob fallback, sample placement, pointwise and span-only nodes, statuses and zero-fill from the host and
      through the context, lookahead, fan-out, determinism, no allocation while querying, the busy guard), `test_scratch.c` (arena sizes, `canopy_scratch`);
      `tests/python/test_engine.py` (Python big-integer reference for sample placement, 110 random graphs against a recursive evaluation bit for bit,
      exported-function check, a thread test of the knob table).
- Verified (ran it): 84 deliberate faults in the engine code (`dev/mutation/step3.py`: wrong limits, missing zero-fills, missing checks, wrong sample
  times, leaks, writes one float past `out`...), each followed by the whole suite, are all detected: 81 in one full run on the final code, the last 3
  (writes past `out`) in a separate run; 13 of the 84 only because the C test program crashed, which is a blunt but valid detection. The campaign
  found weak tests, now fixed: scratch was never really tested as refused outside a query (the test node declared no buffers), a kept shared resource
  was not tested when the same graph is installed again, a node ID coming back with another type was not tested to get knobs of its own, and the
  arena-size limit test was too lenient. The debug-heap run (every heap operation validates the whole heap, leaks reported) passes.
  Throwaway measurements (optimised build, trivial test nodes, one machine: indicative only): a span handler costs about 0.4 to 0.7 ns per sample
  per node, a pointwise node's derived span about 5.7 ns per sample per node, a point query about 6 ns per node; 4 threads with an instance each
  answered 2.8 million 512-sample blocks through a 10-node chain while a fifth thread wrote a knob 68 million times: every block consistent, no leak.
  The recursion depth: a chain of 3000 nodes is answered on a 1 MiB stack and 4000 overflow it (about 280 bytes of stack per node); on a 256 KiB
  thread stack at least 800 work. Nothing guards against a deeper chain (the pull design recurses once per node; a real graph has tens of nodes).
- Believed, not verified: that the memory ordering of the knob slots is sufficient on other CPUs (x64 only has been run); that the engine behaves with
  hundreds of thousands of nodes (not measured); that a debug build of the library behaves like the optimised one on other compilers (only MSVC).
- Done: 106 passed, 0 failed (84 C tests, each run twice, the second time against the debug heap, plus 22 Python tests).

### Step 4 - shared values, generation numbers, compile-and-swap, internal rate. Recommended effort: MAX - DONE (build 5)
- [x] Asked and decided (see "Decisions recorded at step 4"): how an instance adopts a new graph without allocating in the audio thread (packages
      prepared by the editing thread) and where the hidden node lives (registered only by `canopy_registry_add_test_nodes`).
- [x] Generation numbers (`canopy_install.c`, `canopy_core.h`, `canopy_instance.c`): every knob slot (since step 3), every boundary slot (types with
      the built-in-only flag `CANOPY_FLAG_BOUNDARY_SLOT`; step 5 adds the node types), every shared resource (`canopy_ctx_shared_changed`) and every
      setting (bumped at an install when its value differs from the installed graph's) has a generation number. The compiled graph lists for each
      node the counters of the sources upstream of it (itself and loops included) and keeps a digest of identities, wiring and setting numbers made
      at compile time; `canopy_ctx_upstream_stamp(ctx)` folds the current counters into it: one 64-bit stamp, which a node keeps with its checkpoints.
- [x] Records per node ID and node type (`canopy_install.c`): knob slots, boundary slot, shared resource, the settings' numbers and a never-reused
      `uid`; kept while any retained graph holds the node, destroyed (`destroy_shared`) with the last one.
- [x] Compile-and-swap (`canopy_install.c`, `canopy_package.c`): an install is a transaction (all the allocating first, rolled back completely when
      memory runs out) that then publishes the graph and queues, for every live instance, a package built by the installing thread. An instance
      applies its packages at the start of its next host query (`canopy_instance_adopt`: pointer swaps only; nothing allocated, freed or locked).
      State carries over by node ID and type, new nodes get fresh state, a bigger arena is made beforehand; the editing thread later destroys what the
      instance has finished with and frees the compiled graphs no instance can use (at an install, `canopy_instance_free` and `canopy_engine_collect`).
- [x] The engine's lock (`CanopyLock`, an SRW lock): exclusive for installing, making and freeing instances and collecting; shared for knob and
      boundary writes, actions and the counts; never taken by a query.
- [x] The hidden filter `test_filter` (`src/canopy_test_nodes.c`): checkpoints, a cursor, the internal sampling rate, linear resampling at the edges.
- [x] Tests: `tests/c/test_state.c` (the stamp for every kind of source and every kind of change; the filter against a plain recomputation for
      several rates, in any order, with spans, two instances, checkpoints counted through the source it reads, edits upstream, a source that moves by
      0.001 per nanosecond to pin the grid times, enormous checkpoint intervals), `test_swap.c` (adoption at the next query and not before, nothing
      allocated by it, state carried by ID and type, several installs before one query, the arena, idle instances, reclaiming at install and at
      `canopy_instance_free`, shared resources of removed nodes, an out-of-memory sweep over every allocation of an install, three reader threads
      while 400 graphs are installed, the lock held by the test itself while every kind of call is tried, 40 nodes added in any order),
      `test_time.c` (`canopy_frame_to_ns`), `test_registry.c` (the boundary flag), `tests/python/test_filter.py` (an independent big-integer model
      of the filter, edits through the engine, threads).
- Verified (ran it): `python run_tests.py`: 157 passed, 0 failed: 129 C tests, each run three times (normally; against the MSVC debug heap with
  whole-heap validation and a leak report; under AddressSanitizer), plus 28 Python tests.
  The mutation check on the new code, `dev/mutation/step4.py` (135 deliberate faults in the records, stamps, setting numbers, packages and adoption,
  reclaiming, the rollback of a failed install, the filter, `canopy_frame_to_ns` and the lock, each followed by the whole suite): all 135 are
  detected, 21 of them only because the test program crashed or hung (a hang is stopped by the runner's new timeout, `CANOPY_TEST_TIMEOUT`), the
  rest by a named failing test. The first run found five gaps in my tests, now closed (each of the five faults is caught): only an explicit
  `canopy_engine_collect` was tested to free old graphs, not the freeing that an install and `canopy_instance_free` do; the test of an enormous
  checkpoint interval did not run past the first second at 384 kHz, where the overflow first matters; an install that fails for lack of memory was
  not checked to say why; the out-of-memory sweep never made an instance prepare a bigger arena, so leaks on that path were invisible; a plug-in
  type was not tested to be refused a boundary slot. Two faults did not compile at first and were rewritten.
  The 83 faults of step 3 (its spec rewritten where the code moved at this step; three entries about fields that no longer exist were dropped),
  re-run on the new code: all caught, 15 of them by a crash.
  Threads: a test of mine from earlier in this step could pass or fail with the scheduler (its readers got no time during 400 fast installs); it
  failed once, and the installs are now paced by the readers' progress. After that the C program ran 120 times in four parallel loops and 40 times
  more while two mutation campaigns used the machine, the Python thread tests six more times: no failure. A C test holds the engine's own lock and
  checks that queries go through while every other kind of call waits; the faults that drop one of those locks are caught by it.
  Measured (throwaway programs, optimised build, quiet machine, two runs that agree; a chain of N `test.gain` nodes, the worst case for the
  upstream lists): installing (compile and install, in the editing thread) takes 4 us for 10 nodes, 115 us for 100, 8.7 ms for 1000 and 53 ms for
  2500, holding 1 KB, 81 KB, 7.8 MB and 49 MB of upstream counters; the first query after an install (the adoption, in the querying thread) costs
  nothing measurable for 10 or 100 nodes (inside the noise) and about 5 us more for 1000 (a point query through those chains: 0.1, 0.9, 8 us);
  reading the stamp costs about 2 ns per upstream counter (0.2 us for a cone of 100 gain nodes, 2 us for 1000); an instance that never queries
  keeps 0.7 KB per install for a chain of 10, 114 KB for 100, 8.7 MB for 1000.
- Believed, not verified: that the memory ordering of the package hand-over and of the generation numbers is right on CPUs other than x64
  (acquire/release pairs where it matters, reasoned through; only x64 has been run and MSVC has no ThreadSanitizer); that two different states never
  give the same 64-bit stamp (a single change always changes it; two changes may cancel with probability about 2^-64); that the engine copes with
  hundreds of thousands of nodes (not measured, and the upstream lists are quadratic for chains); that handlers running under the lock are fine in
  practice (nothing slow runs there yet).
- Done: 157 passed, 0 failed (129 C tests, each run three times, plus 28 Python tests).

### Step 5 - boundary nodes. Recommended effort: MEDIUM-HIGH - DONE (build 6)
- [x] Asked and decided (see "Decisions recorded at step 5"): the C host calls, by name only; a name is any non-empty text, unique.
- [x] `src/canopy_boundary.c`: the built-in types `boundary_inlet` (outlet `out`; the value the host wrote, for any t, point and span; any float) and
      `boundary_outlet` (inlet `in`, knob when unconnected, no outlet, no handler), both with the text setting `name` (empty at first) and a text
      widget for it. Every registry made by `canopy_registry_new()` has them (`canopy_registry_new_empty()` is for tests that count types).
- [x] Compile: a boundary node (type flag `CANOPY_FLAG_BOUNDARY_NODE`, built-in only; the registry insists it has a STRING setting `name`) whose name
      is empty, or a name used by two nodes of either kind, is a `CANOPY_ERR_GRAPH` fault naming the node(s); the compiled graph keeps the boundary
      nodes sorted by name for binary search.
- [x] Host calls (`canopy_engine.h`): `canopy_engine_set_boundary(engine, name, value)` (an atomic store into the node's slot, bumping its
      generation number; any thread), `canopy_engine_boundary_count`, `canopy_engine_boundary_at(engine, index, name, capacity, &length, &kind,
      &node_id)`, `canopy_instance_read_at(instance, name, t)` and `canopy_instance_read_span(instance, name, t0, t1, n, out)`.
- [x] Tests: `tests/c/test_boundary.c` (12 tests: the types, writing and reading, any float, through a graph, knob fallback, every refusal,
      every kind of bad name, any text as a name, the listing, what a value belongs to, a new graph adopted before the name is looked up, a writer
      against three readers), `tests/python/test_boundary.py` (5 tests through ctypes, with Python in the middle of the graph), the lock test in
      `test_swap.c` now also tries the by-name write and the listing; `dev/mutation/step5.py`.
- Verified (ran it): `python run_tests.py`: 178 passed, 0 failed: 145 C tests, each run three times (normal, debug heap, AddressSanitizer), plus 33
  Python tests. The mutation check on the new code, `dev/mutation/step5.py` (53 deliberate faults in the node types, the registry, the name check, the
  by-name write, the listing and the reads), each followed by the whole suite: all detected, 6 of them only by a crash. The first run found gaps in my
  tests, now closed: a registry that runs out of memory while getting its built-in types was never tested; nothing refused a plug-in type with the
  boundary-node flag or a boundary-node type without a text `name`; a lookup that matched a prefix of a name went unnoticed; the generation number of
  a by-name write was not checked; a span read as the first query after an install was not tested; the lock test did not try the listing call by
  itself. Two faults of mine in the spec (a lock removed without its unlock) and two that did not compile were rewritten. The older specs (step 3
  and 4) still match the code (three entries re-pointed) and the affected faults of step 4 and 3 were re-run: caught. The C program ran 40 times in a
  row and the boundary Python tests 5 times: no failure.
  Found on the way: a Python thread test whose assertion failed left its reader threads running, so the process never ended and a mutation run hung for
  ever; the thread tests now stop their threads in a `finally`, and `run_tests.py` ends a Python test that runs over 30 s (the C programs: 180 s).
- Believed, not verified: that a host with many boundary nodes is fine (the lookup is a binary search, not measured); the Python names and the
  `QueryError`/`GraphError` mapping are step 9's.
- Done: 178 passed, 0 failed (145 C tests, each run three times, plus 33 Python tests).

### Step 6 - FileReadNode. Recommended effort: HIGH - DONE (build 7)
- [x] Asked and decided (see "Decisions recorded at step 6"): the download of dr_wav.h, how replaced samples are freed, how a node shows a message, when
      the file is read.
- [x] `third_party/dr_wav.h` (v0.14.6, 369,705 bytes, SHA-256 in `third_party/README.md`), compiled only in `src/canopy_fileread.c`, allocating
      through `canopy_alloc`.
- [x] Retiring data (`src/canopy_retire.c`): `canopy_ctx_retire(ctx, block, release)`: every host query makes its instance's epoch odd for its
      duration; retiring records the instances that are inside a query and frees the block once each has left it (at once when none is; later by the
      thread that installs, collects or frees an instance); nothing is locked, allocated or freed in a query. If there is no memory to note who to wait
      for, the call waits for the queries itself.
- [x] Node messages: `canopy_ctx_set_message(ctx, text)` (kept in the node's record, at most 255 bytes, cut at a character boundary, never needs
      memory) and `canopy_engine_node_message(engine, node_id, buffer, capacity, &length)`.
- [x] `file_read` (built in, in every registry): path setting `path`, button "Open...", outlets `left` and `right`; PCM 8, 16, 24, 32 and float32 through
      dr_wav; mono feeds both; more than two channels use the first two; silence outside the file; linear interpolation (spans: the point query at each
      sample time); loaded at creation and on the action "open" only; a failed load keeps the old file and puts a message on the node; a good one
      clears the message, replaces the samples with one atomic swap, retires the old ones and calls `canopy_ctx_shared_changed`.
- [x] Tests: `tests/python/test_fileread.py` (generated WAV files of every format against an independent model: bit-exact interpolation at grid and
      off-grid times and beyond the edges, spans of any density and direction, mono/3-channel/1-frame/empty files, every refusal and its message, a
      failed open keeping the old file, when the file is read, UTF-8 paths, a file shorter than its header says), `tests/c/test_retire.c` (data kept
      while a query may read it, freed when it is over, a later query does not hold it back, an instance freed meanwhile, no memory, messages),
      `tests/c/test_fileread.c` (300 replacements of the file under three reader threads, out-of-memory sweeps of "open" and of installing a graph
      with a file, the stamp downstream, queries allocate nothing); `dev/mutation/step6.py`.
- Verified (ran it): `python run_tests.py`: 200 passed, 0 failed: 161 C tests, each run three times (normal, debug heap, AddressSanitizer), plus 39 Python
  tests. The mutation check on the new code, `dev/mutation/step6.py` (64 deliberate faults in retiring, the epochs, messages, loading, the node and its
  answers), each followed by the whole suite: all detected, 6 of them only by a crash. The first run (65 faults) found gaps in my tests, now closed:
  retiring with no engine; a good open after a failed one not clearing the message; a span of a node with no file; the registry entry of the node
  (button, outlets, setting); that any action other than "open" must not read the file. Three faults of mine in the spec did not compile and were
  rewritten, one (a file shorter than its header says) is equivalent because dr_wav already clamps the frame count, and was dropped; that clamping is
  itself tested with a header that claims 4 GB in a 40-byte file. The older specs were re-run on the new code in three parallel copies of the project
  (the host entries changed): step 3 all 83 caught, step 4 133 of 134 (the one left, the lock of the internal by-ID boundary write, is only called by
  tests since step 5 and was dropped), step 5 all 53; three entries whose text moved were re-pointed first.
  Measured (throwaway programs, optimised build, quiet machine): a host query of a bare inlet costs 5.0 to 5.7 ns without the two epoch increments and
  5.3 to 6.3 ns with them (the difference is inside the noise, under 1 ns); the file node: loading a 10 s stereo float file at 48 kHz (3.8 MB) takes
  5.5 ms, pressing open again 1.4 ms, a span of 512 samples at the file's own density 4.8 ns per sample, a point query 13 ns.
  The stress: 300 replacements of the file under three reader threads (under AddressSanitizer too: no read of freed memory); a query held inside a
  handler keeps the replaced samples alive, a query that begins after the swap does not; the fallback when retiring has no memory to note who to wait
  for blocks until the running query ends.
  Found on the way: a Python thread test whose reader threads outlived a failed assertion hung the whole run (fixed with `finally`, and the runner now
  ends a Python test after 30 s); and a message that had to be allocated could not be stored when memory had run out, exactly when a node most needs
  to say "out of memory": messages now live in a 256-byte buffer in the node's record.
- Believed, not verified: that the ordering of the epoch increments and the pointer swap is right on CPUs other than x64 (all of them sequentially
  consistent, reasoned through as the usual store-load pattern; only x64 has been run); dr_wav's robustness against deliberately hostile files (no
  fuzzing; it clamps sizes, and an allocation that fails is reported as "out of memory"); that files of hundreds of MB are fine (the whole file is
  read in one go on the thread that presses open; 3.8 MB takes 5.5 ms, so a 1 GB file would take about 1.5 s there).
- Done: 200 passed, 0 failed (161 C tests, each run three times, plus 39 Python tests).

### Step 7 - realtime preview node and audio device. Recommended effort: MAX
- [ ] miniaudio device ownership in C; play, pause, a settable time, device selection by name (default if missing), 48000 Hz, chunks of at most
      65536, no Python in the audio callback, silence after the end, left+center / right+center with clipping.
- [ ] The warning for graphs containing nodes without the `realtime_safe` flag (it warns; it does not refuse).
- [ ] Tests on miniaudio's null backend; a manual listening check by the author (I cannot hear it), plus a throwaway test that the callback never
      blocks or allocates.
- Done when: the null-backend tests pass and the author has listened to a real device.

### Step 8 - Python graph model and serialization. Recommended effort: HIGH
- [ ] `Graph`: add/connect/disconnect/remove, node IDs (never reused), settings, knobs, boundary names, the loop check and `loop_protection`
      (saved), `to_dict` / `from_dict` (format `canopysynth-graph`, version 1, permanent keys, migrations by type version).
- [ ] Rejections of design section 14 (unknown node type) and the tolerant load of a missing WAV.
- Done when: round-trip tests pass, a hand-written version-1 file is pinned as a fixture, and loops are refused unless protection is off.

### Step 9 - Python bridge: Engine and Instance. Recommended effort: HIGH
- [ ] ctypes loader with the version check; `Engine`, `new_instance`, `value`, `audio` (memoryview of float32), `set_boundary`,
      `boundary_nodes`, `QueryError`, `GraphError`; one instance per thread; the GIL released during queries.
- [ ] Tests: the API sketch of design section 15 runs as written; error cases of section 16.
- Done when: the section 15 snippet works end to end without the editor.

### Step 10 - editor: canvas, nodes, connections. Recommended effort: HIGH
- [ ] tkinter canvas widget: node drawing, ports, connections, dragging nodes, drawing connections from outlet to inlet (fan-in impossible, loops
      refused by default), scroll-wheel zoom, Shift/Alt scroll, middle-drag pan, the right-click add-node list.
- [ ] Tests with the headless stub approach where possible; a real-window check script that drives the widget with synthetic events.
- Done when: the real-window check passes and the author has tried it.

### Step 11 - editor: knobs, widgets from data, node menus. Recommended effort: MEDIUM-HIGH
- [ ] Knobs on inlets (gray when connected, double-click to type a value, raw -1..1 display); widgets drawn from the descriptors' data (button,
      text, choice, label); right-click node menu (delete, rename for boundary nodes, "internal sampling rate..." for nodes that have one);
      connection menu (delete); the loop-protection toggle.
- Done when: every widget kind renders from data, and the menus do exactly what design section 13 lists.

### Step 12 - editor integration and live editing. Recommended effort: HIGH
- [ ] Editor edits trigger compile-and-swap on the Engine; the FileReadNode "open" button and error text; the preview node's play, pause, time field
      (hh:mm:ss.mmm), device list and warning display; compile errors shown while the previous graph keeps running.
- Done when: editing during playback works with the null backend in a throwaway script, and the author confirms it with a real device.

### Step 13 - whole-system verification. Recommended effort: MAX
- [ ] Determinism recordings, a multi-thread stress script (instances + edits + boundary writes + the preview), error behaviours, the C-level
      checks for overruns, timing measurements. Report what was measured.
- Done when: all checks pass and the measurements are recorded here.

### Step 14 - documentation and packaging. Recommended effort: MEDIUM-HIGH
- [ ] Ask the packaging question. Write the user documentation (the public helper functions documented as such), a node-author guide for the
      registration API, and the packaging.
- Done when: a fresh checkout builds, installs and runs the section 15 snippet.

### Step 15 - final audit against the design. Recommended effort: HIGH
- [ ] Walk `canopy_design.md` statement by statement against the "Design coverage" table; list anything unbuilt or built but not in the design;
      ask the author about each difference.
- Done when: the table is complete and the author accepts the audit.

## Design coverage (which step builds which part of canopy_design.md)

| Design section | Step(s) |
|---|---|
| 1 What CANOPY is, 2 Non-goals | all (R1); audited in 15 |
| 3 Vocabulary | 14 (documentation uses the terms) |
| 4 Time (helpers) | 1 |
| 5 Queries (point, span, errors, determinism, `out`) | 1, 3, 9 |
| 6 Inlets and knobs | 3 (behaviour), 11 (editor) |
| 7 History, generation numbers, internal rate | 4 |
| 8 Loops, threading, engine, scratch arena | 3, 4, 8 (loop check), 9 |
| 9 Realtime preview node | 7, 12 |
| 10 Boundary nodes | 5, 9 |
| 11 Built-in nodes | 4 (test node), 5, 6, 7 |
| 12 Registration API, build, distribution | 0, 2, 3, 14 |
| 13 Editor | 10, 11, 12 |
| 14 Serialization | 8 |
| 15 Python API | 8, 9, 12 |
| 16 Errors | 3, 6, 8, 9, 12 |
| 17 Not in version 1 | not built (audited in 15) |

## Progress log (update at the end of every step)

| Step | Status | Notes |
|---|---|---|
| 0 | done (build 1) | MSVC build.ps1, run_tests.py, layout, folder CLAUDE.md; vendoring moved to steps 6 and 7 |
| 1 | done (build 2) | helpers in C and Python, sample placement in C; bug found and fixed by the big-integer cross-check |
| 2 | done (build 3) | registry + descriptor + status codes + version checks; decisions recorded |
| 3 | done (build 4) | graph, engine, instances, queries, scratch arena; 84 deliberate faults all detected; debug-heap run; two design questions for steps 4 and 6 recorded |
| 4 | done (build 5) | generation numbers and stamps, records per node ID and type, compile-and-swap by packages prepared by the editing thread, the engine's lock, the hidden filter; 135 deliberate faults all detected (5 gaps in my tests found and closed on the way), the 83 faults of step 3 re-run on the new code; the C tests now also run under AddressSanitizer; decisions recorded, known limits measured |
| 5 | done (build 6) | boundary inlet and outlet types, unique non-empty names, host calls by name, listing; mutation-checked; registry now holds the built-in types |
| 6 | done (build 7) | dr_wav vendored; retiring of replaced data with per-instance epochs; node messages; the file_read node; mutation-checked |
| 7 | not started | |
| 8 | not started | |
| 9 | not started | |
| 10 | not started | |
| 11 | not started | |
| 12 | not started | |
| 13 | not started | |
| 14 | not started | |
| 15 | not started | |
