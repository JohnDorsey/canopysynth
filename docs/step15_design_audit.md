# CANOPY - audit of version 1 against `canopy_design.md` (plan step 15, build 19)

**Afterwards (build 20):** the author answered all nine differences: A1 the arrow language was removed from the design; A2 to A9 were accepted as recommended and the design text was amended to match (each amendment is marked "added at step 15" or "as built" in `canopy_design.md`); the public text now says "connection". The tables below are as audited.

Every statement of the design was checked against the code and the tests by three readers working on separate sections (sections 1-3, 13 and 17; 4 to 8; 9 to 12 and 14 to 16), who read the code and the assertions of each test they cite
and ran a sample of the tests and some throwaway scripts of their own. I (the assistant) checked the findings that matter by running them myself: they are marked **(I ran it)**. The statuses:

- **TESTED**: the code does it and a test asserts it (the test is named, abbreviated: all are `test_py_...` or `test_c_...`; `TP` is `tests/python`, `TC` is `tests/c`).
- **UNTESTED**: the code does it, no test asserts it specifically. **CLOSED** after it: a test written for this audit (`tests/python/test_audit.py`) now does.
- **DIFFERS**: the code does something other than the words of the design (and whether the author approved it).
- **N/A**: a rationale, a definition, a permission or an absence with nothing to run.

**Summary.** About 250 statements. 0 are NOT BUILT. 9 DIFFER in some way (section "Differences" below: A6 is a change the author approved that the design text does not say, A3 is implied by the design's own snippet, and the other 7 need the author's answer). 7 were UNTESTED, 3 of which are now closed by tests; 4 remain (contracts on node authors, which no test can see, and one
working feedback loop). The rest are TESTED or N/A. `docs/canopy_plan.md` ("Design coverage") holds the table by section.

## Differences (each needs the author's answer: see the plan, "Step 15")

| ID | Design says | Code does | Approved? |
|---|---|---|---|
| A1 | 3: a connection is "shown as an arrow in the editor" | the editor draws a plain blue S-curve with no arrowhead (`create_line` without `arrow=`: **I ran it**: no `arrow` option anywhere in `canvas.py` for wires); direction is shown only by outlets on the right and inlets on the left | no |
| A2 | 3: a connection is "always called 'connection' in code and docs" | the public API, the C API and the menus say connection; the editor's internals (`_wire`, the `wire:` canvas tags), `README.md` ("You wire nodes together"), two sentences of `docs/user_guide.md` and a docstring in `graph.py` say "wire"; internals also say `_links` | no |
| A3 | 3: BoundaryInletNode, BoundaryOutletNode, FileReadNode | no identifier has these names: node types are `boundary_inlet`, `boundary_outlet`, `file_read` (the design's own section 15 snippet uses these keys) | implied by section 15 |
| A4 | 14: "Node IDs are never reused within a graph" | true while the `Graph` object lives; **not across save and load**: the file has no counter, so after deleting the highest node, saving and loading, the next node gets that ID again (**I ran it**: 3 was reused). Plan step 8 decision 4 records it as the model's choice | no |
| A5 | 9: the preview "warns about graphs containing nodes not flagged realtime_safe" | it warns about such nodes that **feed that preview** (the ones its audio thread runs); a non-safe node elsewhere in the graph gives no warning | no (plan step 7 decision 7, "mine") |
| A6 | 5: "a point query is not defined as a special case of a span query" | for a node with only `query_span` the engine answers a point query with `query_span(t, t, 1)`; a node with both gets two separate calls | **yes**, step 3; the design text was not changed |
| A7 | 7: a node's checkpoints "store the generation numbers they were made under" and compare them; each source has "an atomic generation number" | a node reads one 64-bit digest (`canopy_ctx_upstream_stamp`) and compares that; the generation number of a *setting* is a plain counter changed only inside an install, folded into the digest. The knob, boundary and shared-resource numbers are atomic. A collision is possible in principle (about 2^-64 per comparison) | no (plan step 4 choice 1, "mine") |
| A8 | 7: "no registry of instances is needed"; 8: "one shared table of atomic floats" | staleness detection uses no registry and no push, as written; but the engine keeps a list of live instances for the compile-and-swap packages, and the slots live in one record per (node ID, type) in a sorted array, not one table. Each slot is an atomic float with its generation, as written | no (plan step 4 choice 6) |
| A9 | 2: "no menu bar", "no file exports" | the **`Editor` widget** has neither (**I ran it**: the root's `menu` stays empty); the stand-alone **host program** `canopysynth/app.py` (`python -m canopysynth`, `run_editor.bat`, the `canopysynth-editor` entry point of the wheel) has a File menu (New, Open, Save, Save as, Quit) and writes the graph as JSON | no ("choice of mine" at step 14) |

Also noted, no decision needed: **6** says a knob "displays its raw -1..1 value": it is shown on hover, while dragging and in the typing box, not permanently on the dial (plan step 11 decision 2; the author has used the editor); after a **failed Open** the editor has
already stored the new path in the node's `path` setting while the engine goes on playing the old file (**I ran it**, from the code: `_open_file` sets the setting first; the author tried a bad file at step 12 and was content), so the saved graph holds the path that failed; `Engine.set_knob` is not kept by the next `Engine.update()` (the Graph's knob is written back: documented in the user guide; the editor does both).

## Statement by statement

### 1 What CANOPY is, 2 Non-goals, 3 Vocabulary

| # | Statement | Status | Evidence |
|---|---|---|---|
| 1.1 | name CANOPY; package and import name `canopysynth` | TESTED | TP package: wheel metadata `Name: canopysynth`, pip install and import from a fresh venv |
| 1.2 | standalone, no dependency on PrismaticFractals | UNTESTED (absence, by search: no occurrence anywhere) | the wheel installs with `--no-deps` and runs |
| 1.3 | manipulating audio and building effects by linking nodes | N/A | the mechanism exists; version 1 has 4 nodes and no processing nodes (17) |
| 1.4 | embedded in a tkinter program, as a panel next to the host's controls | TESTED (CLOSED) | `Editor(tk.Frame)`; `test_audit`: `the_editor_is_a_tk_frame_that_packs_to_the_right_of_the_hosts_own_controls` |
| 1.5 | purpose: audio for the video, audio-driven data | N/A | the mechanism is section 15 |
| 1.6 | minimalist | N/A | 4 node types, 429 KB DLL importing only KERNEL32 (TP package) |
| 1.7 | processing in C | TESTED | all handlers in `src/`; the Python side holds the model and the editor |
| 1.8 | fast enough for realtime | measured, not asserted | `docs/step13_measurements.txt`; the author's listening check (step 7) |
| 1.9 | realtime used only by the preview node | TESTED | only `canopy_audio.c` and `canopy_preview.c` touch the device; the preview callback tests |
| 1.10 | the visual editor is Python | TESTED | `canopysynth/editor/` |
| 2.1 | no animation system, keyframes or timeline | absence, by search | - |
| 2.2 | no global playback state | absence, by search | playback exists only inside each preview node |
| 2.3 | no global "current time" | absence; determinism tests | TC determinism: answers depend only on the query's time |
| 2.4 | no menu bar | DIFFERS at package level (A9); the widget is clean | TP editor: no menu configured |
| 2.5 | no file exports | DIFFERS at package level (A9: graph JSON); no audio export (dr_wav's writer is compiled but never called; miniaudio encoding is off) | - |
| 2.6 | no undo/redo | absence, by search | deleting needs no confirmation |
| 2.7 | (to start with) no copy/paste | absence, by search | only Tk's own text copy in text boxes |
| 3.1 | node with an integer ID | TESTED | TP graph: IDs go on after the highest |
| 3.2 | every inlet has a knob | TESTED | TC knobs start at the default; TP editor_controls: every unconnected inlet shows its knob |
| 3.3 | outlet answers as a function of time(s) | TESTED | TC query tests |
| 3.4 | connection: outlet to inlet, "shown as an arrow", "always called connection" | DIFFERS (A1, A2) | wires are arrow-less S-curves |
| 3.5 | knob | TESTED | TP editor_controls drag and type tests |
| 3.6 | setting | TESTED | TP graph to_dict; TC registry |
| 3.7 | BoundaryInletNode / BoundaryOutletNode | DIFFERS in spelling (A3); behaviour TESTED | TC boundary |
| 3.8 | channel: one mono stream per connection | TESTED (implicitly) | one float array per outlet |
| 3.9 | compiled graph: immutable | TESTED | TC swap; TP editor_link: a graph that cannot be compiled leaves the previous running |
| 3.10 | instance | TESTED | TC instance, stress |
| 3.11 | generation number: atomic counter per source | TESTED, with the setting nuance (A7) | TC state |
| 3.12 | internal sampling rate | TESTED | TC registry, TP editor_controls |
| 3.13 | public helper functions | TESTED | TP time |
| 3.14 | FileReadNode | TESTED (named `file_read`, A3) | TP fileread |
| 3.15 | realtime preview node | TESTED (named `realtime_preview`) | TP preview |
| 3.16 | timestamp: UI text, never inside CANOPY | TESTED | only `editor/timetext.py` knows hh:mm:ss.mmm; the engine takes nanoseconds |

### 13 Editor, 17 Not in version 1

| # | Statement | Status | Evidence |
|---|---|---|---|
| 13.1 | add nodes by right-clicking the background and choosing from a list | TESTED | TP editor: the add menu lists built-in types first and hides the test type; choosing an entry adds the node at the clicked point |
| 13.2 | zoom: the scroll wheel | TESTED (synthetic events; real touchpad "believed") | TP editor: the wheel zooms around the pointer |
| 13.3 | horizontal scroll: Shift+wheel | TESTED (synthetic) | same test |
| 13.4 | vertical scroll: Alt+wheel | TESTED (synthetic; whether Windows delivers Alt+wheel to the canvas on a real mouse is believed, not verified) | same test |
| 13.5 | pan: middle-click drag | TESTED | same test |
| 13.6 | scrollbars are not a concern | N/A | the editor has none |
| 13.7 | illegal connections (two outlets to one inlet) impossible | TESTED | TP editor: refused connections change nothing; pressing a connected inlet starts no wire; TP graph fan-in refused |
| 13.8 | (by default) connections that would form a loop impossible | TESTED | TP graph loop protection (default True); TP editor refusal with the reason |
| 13.9 | the way to turn it off | TESTED | TP editor_controls: the background menu switch; `graph.loop_protection = False` |
| 13.10 | (delegated) nodes are moved by dragging | TESTED | TP editor: dragging a node |
| 13.11 | (delegated) connect by dragging outlet to inlet | TESTED | TP editor: dragging from an outlet to an inlet (and from a free inlet) |
| 13.12 | (delegated) delete a node from its menu | TESTED | TP editor_controls |
| 13.13 | (delegated) delete a connection from its menu | TESTED | TP editor_controls: right-click a wire, or a connected inlet |
| 13.14 | (delegated) rename a boundary node from its menu | TESTED | TP editor_controls; empty or taken names are refused |
| 17.1 | no copy/paste | absent | see 2.7 |
| 17.2 | no undo/redo | absent | see 2.6 |
| 17.3 | no relative paths | TESTED (refused) | TP graph absolute-path tests; TP fileread |
| 17.4 | no placeholders for unknown node types | TESTED (the whole file is refused) | TP graph |
| 17.5 | no checkpoint memory cap | absent | - |
| 17.6 | no knob values in real units | TESTED | TP editor_controls: hovering shows the raw value |
| 17.7 | no processing nodes | TESTED | TP graph: the default catalog is exactly the 4 built-in types. **Note:** `examples/example_node.c` is a processing node (`example.scale`), shipped as a worked example of a third-party node (step 14); it is not registered by default |
| 17.8 | no numba or Python node tiers | absent | `canopysynth.node` does not exist; Python node types exist only in tests (`engine_dll.py`) |

### 4 Time, 5 Queries, 6 Inlets and knobs

| # | Statement | Status | Evidence |
|---|---|---|---|
| 4.1 | times are signed int64 nanoseconds | TESTED | TP bridge: times must be 64-bit integers |
| 4.2 | negative times are legal | TESTED | TC query: placements with -5; TC time |
| 4.3 | no global sample rate | N/A | absence |
| 4.4 | `frame = floor((ns*rate + 500_000_000)/1e9)`, round half up | TESTED | TC time; TP time: against big integers (about 80 000 cases) |
| 4.5 | overflow-safe split, no 128-bit integers | TESTED | TC time: int64 limits; no `__int128` in `src/` |
| 4.6 | blocks `frame(t1)-frame(t0)` tile exactly | TESTED | TC time; TP time |
| 4.7 | rates 1 to 9223372036 Hz; others are errors | TESTED | TC and TP time |
| 4.8 | a frame that does not fit int64 is an error | TESTED | same |
| 4.9 | second helper: frame plus fraction | TESTED | TP time: against exact fractions |
| 4.10 | both in C and in Python | TESTED | exports test; TP time |
| 4.11 | documented as "public helper functions", with how they are useful | TESTED | TP time: documented as such; the user guide and node author guide; TP docs |
| 5.1 | an outlet is a function; no playback state, no current time | TESTED | determinism tests |
| 5.2 | mono float32 audio, several channels need several connections | N/A | convention |
| 5.3 | no connection types | N/A | the descriptors have no type field |
| 5.4 | point and span queries, one node may use both | TESTED | TC query |
| 5.5 | point query `int query_at(..., t, float *out)`, 0 = success, 0.0 and nonzero on failure | TESTED | TC query: status passed through, answer 0.0 (the approved ABI 2) |
| 5.6 | span query fills exactly n floats, zero-fills on failure | TESTED | TC query; TC overrun (every node, 27 sizes x 16 time shapes) |
| 5.7 | "a point query is not defined as a special case of a span query" | DIFFERS, approved (A6) | TC query: a span-only node answers a point query with a one-sample span |
| 5.8-5.9 | sample placement `t0 + floor(i*(t1-t0)/n)`, via quotient and remainder | TESTED | TC time and query; TP engine and time: against big integers |
| 5.10 | `t1 < t0` plays reversed | TESTED | TC time and query |
| 5.11 | `t1 == t0` puts all samples at t0 | TESTED | TC query |
| 5.12 | n = 0, n < 0, n > 65536 are errors | TESTED | TC query; TP bridge |
| 5.13 | an overflowing `t1 - t0` is an error | TESTED | TC query and overrun |
| 5.14 | a missing connection is not an error: the knob supplies the value | TESTED | TC query, boundary |
| 5.15 | what a point query means between samples is up to the node | N/A | the file node interpolates linearly (TP fileread) |
| 5.16 | a node may query any times, later ones too | TESTED | TC query |
| 5.17 | fan-out allowed | TESTED | TC query |
| 5.18 | fan-in illegal, the editor makes it impossible | TESTED | TC graph faults; TP graph; TP editor |
| 5.19 | edits take effect at the next query | TESTED | TC graph, query, swap; **note** a host that edits the Python `Graph` calls `Engine.update()` itself (documented) |
| 5.20 | no consistent snapshot of an edit during a running query | N/A | a non-promise; the stress oracle encodes what does happen |
| 5.21 | determinism rule | TESTED | TC determinism (12 graphs, three builds); TP determinism; clang gives the same bits (step 14b) |
| 5.22 | the caller owns `out`, exclusively the callee's | TESTED | guarded buffers with canaries |
| 5.23 | `out` may be uninitialised | TESTED | the guarded buffers start with a poison pattern |
| 5.24 | `out` never aliases another buffer of the call | UNTESTED (the engine passes the caller's buffer straight through; arena buffers tested disjoint) | contract on node authors |
| 5.25 | the callee writes all n floats on success | TESTED | TC overrun: every float written |
| 5.26 | the callee does not read `out` before writing, keeps no pointer | UNTESTED | contract on node authors (the built-ins were read: they only write) |
| 5.27 | a caller may read the floats as audio | N/A | permission |
| 5.28 | Python: a span returns a memoryview of float32; numpy not a dependency | TESTED | TP bridge |
| 5.29 | Python: a nonzero status raises QueryError, point as span | TESTED | TP bridge |
| 6.1 | every inlet has a knob | TESTED | TC graph; TP editor_controls |
| 6.2 | declared default knob position, else 0 | TESTED | TC graph; TP graph |
| 6.3 | a connected inlet's knob is hidden, keeps its position, returns on disconnect | TESTED | TC query; TP editor_controls, editor_selection |
| 6.4 | an unconnected inlet answers its knob (-1..1) for any time | TESTED | TC query |
| 6.5 | a span on an unconnected inlet gives the value n times | TESTED | TC query |
| 6.6 | each node maps -1..1 to its own unit | N/A | convention |
| 6.7 | a knob displays its raw -1..1 value | TESTED, narrower reading (hover, dragging, typing box) | TP editor_controls |
| 6.8 | typing a value by double-click (delegated) | TESTED | TP editor_controls |

### 7 History, 8 Loops, threading, engine and editing

| # | Statement | Status | Evidence |
|---|---|---|---|
| 7.1 | no global rule for history | N/A | - |
| 7.2 | the author prefers checkpoints | N/A | built once, in the hidden filter; TC state |
| 7.3 | no checkpoint memory cap | built (nothing to test) | - |
| 7.4 | staleness is detected by pulling | TESTED | TC state |
| 7.5 | every source has a generation number bumped on write | TESTED (A7: settings are not atomic) | TC graph, state, fileread, boundary |
| 7.6 | the compiled graph records the sources upstream of each node | TESTED | TC state: through any number of nodes, fan-in and out, loops, rewiring |
| 7.7 | checkpoints store the generation numbers; mismatch discards | TESTED as a digest (A7) | TC state |
| 7.8 | nothing is propagated, no registry of instances | DIFFERS in the letter (A8) | the engine's instance list serves compile-and-swap |
| 7.9 | internal sampling rate: whole Hz 1..384000, default 48000 | TESTED | TC registry, graph; TP graph |
| 7.10 | asks upstream at that rate, resamples, results do not depend on who asks | TESTED (hidden filter only; no shipped node has the flag) | TC state, determinism |
| 7.11 | grid anchored at t = 0 | TESTED (hidden filter) | TC state, time |
| 7.12 | linear interpolation at the node's edges | TESTED (output edge) | TC state |
| 7.13 | the editor's "internal sampling rate..." item | TESTED | TP editor_controls |
| 8.1 | loops allowed; only the editor refuses to close one | TESTED (the refusal); a working feedback loop is UNTESTED (an auditor's throwaway probe of a self-loop with a base case answered correctly: 50.0 at depth 50) | TP graph, editor; TC graph: loops compile |
| 8.2 | protection can be turned off, saved with the graph | TESTED | TP graph, editor_controls |
| 8.3 | the engine does nothing about loops | built (absence) | TC scratch: the arena returns NULL, not a crash |
| 8.4 | a graph compiles to an immutable compiled graph | TESTED | TC swap, graph |
| 8.5 | one instance per querying thread; no lock on the audio path | TESTED | TC query (busy), swap (queries never wait for the lock), preview (the audio thread allocates nothing) |
| 8.6 | one shared table of atomic floats with generation numbers | TESTED (A8: one record per node, not one table) | TC swap, boundary |
| 8.7 | compile-and-swap, adopted at the next query | TESTED | TC swap; TP editor_link |
| 8.8 | node ID carries state across the swap | TESTED | TC swap |
| 8.9 | three scopes of node data | TESTED | TC graph, swap |
| 8.10 | each instance has a scratch arena | TESTED | TC scratch |
| 8.11 | largest n is 65536 | TESTED | TC query, preview |
| 8.12 | scratch buffers declared per type, arena sized for the deepest chain | TESTED | TC scratch |
| 8.13 | the audio device is owned by C (miniaudio) | TESTED | TC audio, preview, service; TP shutdown |

### 9 Preview, 10 Boundary nodes, 11 Built-in nodes

| # | Statement | Status | Evidence |
|---|---|---|---|
| 9.1 | playback state only inside this node | TESTED | TC preview: two nodes, separate times |
| 9.2 | play and pause buttons | TESTED | TC preview; TP editor_link |
| 9.3 | a text field for a time, hh:mm:ss.mmm | TESTED (an editor-drawn row, not a descriptor widget: the position is not a setting) | TP editor_time; TC preview |
| 9.4 | no outlets | TESTED | TC preview type test |
| 9.5 | other nodes cannot see its state | TESTED | follows from no outlets |
| 9.6 | after the end of the audio it keeps playing silence until paused | UNTESTED, CLOSED | `test_audit`: `after_the_end_of_the_audio_the_preview_goes_on_playing_silence_until_it_is_paused` (null backend; I ran it) |
| 9.7 | a control to select the device, saved by name | TESTED | TP editor_link; TP graph to_dict |
| 9.8 | a missing device falls back to the system default | TESTED (at the first Play, not at load) | TC preview; TP preview |
| 9.9 | opens at 48000 Hz (miniaudio converts) | TESTED on the null device; conversion on real hardware only by the author's listening check | TC audio |
| 9.10 | chunks of at most 65536 samples | TESTED | TC preview |
| 9.11 | three inlets: left, right, center | TESTED | TC preview |
| 9.12 | left+center and right+center, clipped | TESTED | TC preview |
| 9.13 | warns about non-safe nodes, does not refuse | TESTED, narrower reading (A5) | TC preview; TP preview; TP editor_link |
| 10.1 | addressed by name | TESTED | TC boundary; TP bridge |
| 10.2 | names are unique | TESTED | TC boundary; TP boundary; the editor refuses |
| 10.3 | the host can list boundary nodes by name and kind | TESTED | TC boundary; TP bridge |
| 10.4 | a boundary inlet answers the written value for any t | TESTED | TC boundary |
| 10.5 | accepts any float | TESTED | TC boundary: NaN, infinities, -0, subnormals, bit-exact |
| 10.6 | the write is an atomic store | TESTED | TC boundary: readers in other threads; TP boundary |
| 10.7 | a boundary outlet reads with the same two query kinds | TESTED | TC boundary |
| 10.8 | nothing is clamped | TESTED | TC boundary |
| 10.9 | PrismaticFractals clips only when applying | N/A | about a host |
| 11.1 | the file node reads WAV only | TESTED | TP fileread |
| 11.2 | an "open" button | TESTED (the real file dialog is replaced by `file_chooser` in tests; the author used it) | TP editor_link |
| 11.3 | the whole file is loaded into memory | TESTED | TP shutdown (memory refusal) |
| 11.4 | reloaded only when "open" is pressed again | TESTED (a node is also loaded when it first reaches a compiled graph) | TP fileread |
| 11.5 | the path is stored absolute | TESTED | TP graph, fileread |
| 11.6 | uses the file's own rate | TESTED | TP fileread: five formats x 1000 and 44100 Hz against a model |
| 11.7 | resamples when the sample count differs | TESTED | TP fileread |
| 11.8 | linear interpolation for points | TESTED | TP fileread |
| 11.9 | silence before and after | TESTED | TP fileread |
| 11.10 | exactly two outlets, left and right | TESTED | TC fileread |
| 11.11 | mono feeds both; more than two channels use the first two | TESTED | TP fileread |
| 11.12 | PCM 8/16/24/32 and float 32, dr_wav | TESTED | TP fileread; TC wavfuzz |
| 11.13 | anything else is refused | TESTED | TP fileread |
| 11.14 | the set is not expanded | TESTED | TP graph: the default catalog |
| 11.15 | a hidden stateful test node | TESTED | TC state; hidden in the add menu (TP editor) |

### 12 Registration API, 14 Serialization, 15 Python API, 16 Errors

| # | Statement | Status | Evidence |
|---|---|---|---|
| 12.1 | C engine, prebuilt DLL through ctypes | TESTED | TP skeleton, bridge, package |
| 12.2 | the DLL exports a version number the Python side checks | TESTED | TP registry: a DLL of another build or layout is refused |
| 12.3 | WAV parsed with dr_wav | TESTED | - |
| 12.4 | tests run without sound hardware on the null backend | TESTED | every preview test |
| 12.5 | recorded-output tests | TESTED | TC and TP determinism |
| 12.6-12.8 | tiers C, numba, Python; numba and Python not built | C TESTED; the others N/A (section 17) | - |
| 12.9 | one descriptor, first fields `abi_version` and `struct_size` | TESTED | TC registry |
| 12.10 | Python reads the metadata from it | TESTED | TP registry, graph |
| 12.11-12.12 | key rules: built-in flat, others contain a dot | TESTED (stricter: each dotted segment is `[a-z0-9_]+`) | TC registry |
| 12.13 | display name, integer type version | TESTED | TC registry |
| 12.14-12.17 | flags, `internal_sampling_rate` added, key reserved, editor item | TESTED | TC registry; TP editor_controls |
| 12.18-12.20 | inlets, outlets, settings (five kinds) | TESTED | TC registry, graph; TP graph |
| 12.21 | scratch buffers declared | TESTED | TC scratch |
| 12.22-12.24 | widgets in data; bound to a setting or an action | TESTED (that `on_action` runs on the calling thread is not asserted) | TP editor_controls; TC graph |
| 12.25 | handlers | TESTED | TC graph |
| 12.26 | handler signatures | TESTED | `canopy_node.h` matches; every test node compiles against them |
| 12.27 | `CanopyCtx*` opaque, valid until the handler returns, one thread | UNTESTED (a rule on authors; the context is a stack object) | - |
| 12.28-12.29 | `canopy_inlet_at/span`: connected outlet or knob; status passed through | TESTED | TC query |
| 12.30-12.32 | `canopy_scratch`: NULL beyond 65536 or exhausted; released at return; no more than declared; the arena cannot run out in a graph without loops | TESTED | TC scratch |
| 12.33-12.34 | `canopy_ctx_state/shared`; typed setting getters (by index) | TESTED | TC graph |
| 12.35 | pointwise nodes: the span is one point query per sample time | TESTED | TC query |
| 12.36 | a node may implement both | TESTED | TC query |
| 12.37 | Python decorator tier | N/A | not built (17) |
| 12.38 | migrations from each older type version | TESTED, Python side only (the C descriptor has no migration field) | TP graph |
| 14.1-14.5 | dict format, node entries, knobs, x and y, settings under permanent keys | TESTED | TP graph: `to_dict` exactly the documented format; the hand-written v1 fixture |
| 14.6 | connection entries `{from, to}` | TESTED | same |
| 14.7 | permanent string keys | TESTED (a choice is saved as its text) | same |
| 14.8 | node IDs are never reused within a graph | DIFFERS across save and load (A4) | TP graph: within a live graph |
| 14.9 | an unknown node type rejects the whole file | TESTED | TP graph |
| 14.10 | a missing WAV is not an error: silent and flagged | TESTED | TP graph; TP engine_controls |
| 14.11 | no relative paths | TESTED | TP graph, fileread |
| 15.1-15.19 | every line of the snippet | TESTED | TP bridge: the snippet runs as written; `examples/section15.py` runs in the package test (without its window); the audit ran it verbatim, with a real window |
| 15.20 | `canopysynth.Editor(root, graph)` is a tk.Frame | TESTED, CLOSED | `test_audit`: the Frame test |
| 15.21 | `import canopysynth` loads neither tkinter nor the DLL | TESTED | TP graph, editor |
| 15.22-15.24 | QueryError, GraphError, BoundaryError as described, separate classes | TESTED | TP bridge, boundary |
| 16.1 | a missing or unreadable WAV on open: old file kept, message on the node | TESTED | TP fileread; TP editor_link |
| 16.2 | an unknown boundary name raises BoundaryError naming it | TESTED | TP bridge |
| 16.3 | an uncompilable graph raises GraphError with the reason | TESTED | TP bridge; TC graph |
| 16.4 | empty or repeated boundary names raise BoundaryError | TESTED | TP bridge, boundary |
| 16.5 | the editor shows either and keeps the previous graph running | TESTED; the GraphError path was UNTESTED, CLOSED | `test_audit`: the GraphError test (fails when the code only catches BoundaryError: I ran it) |
| 16.6 | a C query reports its status; failed point is 0.0, span zero-filled | TESTED | TC query, boundary |
| 16.7 | Python: every nonzero status raises QueryError | TESTED | TP bridge |

## Built but not in the design (the author may veto any)

**In the C library and its headers:** status codes (14) and `canopy_status_message`; `CANOPY_ERR_BUSY` (an instance refuses a second concurrent use); the exported `canopy_sample_time`; node-author calls `canopy_ctx_upstream_stamp`, `canopy_ctx_shared_changed`, `canopy_ctx_retire`, `canopy_ctx_set_message`;
three flags for built-in types only (`BOUNDARY_SLOT`, `BOUNDARY_NODE`, `SERVICE`); stricter checks on descriptors (default knobs in -1..1, widgets that name existing settings, a node with outlets needs a query handler); engine calls `canopy_engine_set_knob/get_knob/collect/graph_serial/node_count/last_error/action/node_message/
set_audio_backend/audio_devices`, `canopy_preview_state/set_time/warning`, `canopy_instance_inlet_at/span`, diagnostics (`canopy_alloc_live/total`, arena size, serials). 63 functions are exported in all, and a test keeps the export table, the headers and the Python declarations equal.

**In the Python package:** `Engine.update/set_knob/action/node_message/collect/set_audio_backend/audio_devices/preview_state/preview_set_time/preview_warning/close/closed/graph`, `Engine(graph, registry=...)`, `Graph(types=...)`, `Graph.engines/can_connect/has_loop/validate/remove/disconnect/connections/connection_into/node/nodes`, `Node.set/set_knob/x/y/info`,
`NodeTypes`, `register_migration`, `__version__`, `CANOPYSYNTH_BUILD`; exceptions beyond the three named (ValueError, TypeError, OverflowError, RuntimeError, MemoryError); loop protection in the model, which cannot be turned on while a loop exists.

**In the editor:** knobs in pills, marquee selection and moving or deleting a selection, "Disconnect" on a connected inlet, Escape to cancel a wire, Home to fit, port tooltips, a message line, notes under nodes (engine messages and the preview's warning), colours for third-party nodes by realtime safety, boundary nodes auto-named `default0`..., listeners (`add_listener`, `add_action_listener`, `<<GraphChanged>>`), the link to every `Engine` made over the graph.

**In the preview and the file node:** the device opens at the first Play, stays open while paused and closes with the node; typed times round half up to a frame of 48000 Hz; the device list is "(system default)" plus the machine's; NaN plays as silence; a file is loaded when its node first appears; a file shorter than its header says plays as far as it goes; sample rates outside 1..9223372036 are refused.

**Shipped beside the design (step 14):** `canopysynth/app.py`, `__main__.py`, `run_editor.bat` (the stand-alone editor, A9), the wheel and the unzip-and-run folder (`dev/package.py`), `README.md`, `docs/user_guide.md`, `docs/node_author_guide.md`, `docs/THIRD_PARTY_NOTICES.txt`, `examples/` (the section 15 program and a worked C node, which is a processing node: see 17.7), and the tools in `dev/` and `tests/`.
