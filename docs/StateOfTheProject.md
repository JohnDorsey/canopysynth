# CANOPY - the state of the project

Written after plan step 7 (build 8). Steps 0 to 7 are done; the one open item inside them is your listening check of the preview node.

This document is long on purpose. It is written for someone who is fairly new to C and to concurrent programming but who does not want
the vocabulary hidden: every technical term is used by its real name, and explained at the place where it first appears. The last part
(section 12) looks closely at three decisions of mine from the step 7 report (choices 4, 6 and 7) with their alternatives.

A word on honesty, used throughout: "**verified**" means I ran a test or a measurement and saw the result; "**believed**" means I read or
reasoned it through but did not (or could not) run it. The two are never mixed in this file.

Contents

1. What CANOPY is
2. Where things stand
3. A C primer, as much as this project needs
4. A concurrency primer
5. The architecture, from the bottom up
6. The three built-in nodes
7. Step 7 in depth: sound to a real device
8. How the project is tested (and why the tests are shaped this way)
9. Build, files and conventions
10. Measurements
11. Known limits, and what is only believed
12. Three choices examined: 4, 6 and 7
13. What is left to build
14. Glossary

---

## 1. What CANOPY is

CANOPY ("C Audio Nodes in PYthon", import name `canopysynth`) is a library for manipulating audio by connecting **nodes** with
**connections**, the way a modular synthesizer connects modules with patch cables. It is meant to be embedded in other programs. Your
motivating example: a video generator (light_bounces) whose ellipse width could be static, keyframed, or *driven by an audio-derived
number from CANOPY*; and also a source of audio for the video.

The pieces, as designed (the design file `docs/canopy_design.md` is **final**: nothing in it changes without your permission):

- **The engine, in C.** Fast code that answers questions of the form "what is the value of this node's output at time t?". It is built
  into a Windows DLL (`canopysynth.dll`).
- **A Python layer** that loads the DLL with `ctypes` (Python's built-in way of calling C functions) and offers a friendly API. *Not
  written yet* (steps 8 and 9).
- **A tkinter node editor**, drawn in Python, to build graphs by dragging boxes and cables. *Not written yet* (steps 10 to 12).

Deliberate **non-goals**: no animation system, no timeline, no keyframes, no global "current time", no undo/redo, no file export. CANOPY is
a *tool used inside larger programs*; the larger program owns the notion of time and playback.

### The central idea: an output is a function of time

A node's output is not a stream that flows past; it is a **function**: you give it a time, it gives back a number (a `float`). There
is no "now". Two ways to ask:

- **Point query:** "what is your value at time t?" -> one float.
- **Span query:** "give me n samples covering the time span [t0, t1)" -> n floats, written into a buffer you supply.

Times are **signed 64-bit integers counting nanoseconds** since t = 0. (Negative times are legal.) There is no project-wide sample rate;
a node that reads a 44.1 kHz file simply converts as needed. A node may ask other nodes about *any* time, including later times than
the one it was asked about - that is how "lookahead" works with no special mechanism.

A consequence worth internalising: the **same question must always get the same answer** while nothing has been edited (the
*determinism rule*). That is why the build uses `/fp:precise` (no compiler tricks that change floating-point results) and why nothing in
the query path may depend on timing or thread scheduling.

---

## 2. Where things stand

| Step | What | Status |
|---|---|---|
| 0 | skeleton, build, test runner | done |
| 1 | time helpers (ns <-> sample frame), sample placement | done |
| 2 | node-type descriptor, registry, status codes | done |
| 3 | compiled graph, instances, queries, scratch arena | done |
| 4 | shared values, generation numbers, compile-and-swap, lock | done |
| 5 | boundary nodes (host <-> graph) | done |
| 6 | file node (WAV reading), safe replacement of data, node messages | done |
| 7 | realtime preview node, audio device (miniaudio) | **done except your listening check** |
| 8 | Python graph model and serialization | next |
| 9 | Python bridge (`Engine`, `Instance`) | |
| 10 | editor: canvas, nodes, connections | |
| 11 | editor: knobs, widgets, menus | |
| 12 | editor integration, live editing | |
| 13 | whole-system verification | |
| 14 | documentation and packaging | |
| 15 | final audit against the design | |

**Numbers (verified, last full run):** 264 tests pass, 0 fail. That is 219 C tests, each run **three times** (normally, against the MSVC
debug heap, and under AddressSanitizer), plus 45 Python tests. The "mutation check" (section 8.5) has deliberately broken the code in
476 specific ways across steps 3 to 7; every break was detected.

**Size:** the C library is about 4,800 lines in 21 files under `src/`, plus two vendored third-party headers (`dr_wav.h` for reading
WAV files, `miniaudio.h` for talking to sound hardware) that are far larger than our own code.

**Open item:** run `python dev/listen_check.py` and tell me what you heard. Nothing in this environment can hear, so "the sound is right"
is, for now, *believed* (the numbers handed to the device are verified exactly; whether they come out of the speakers correctly is not).

---

## 3. A C primer, as much as this project needs

You don't need all of C to follow this project. You need about ten ideas.

### 3.1 Source files, headers, and the DLL

C code lives in `.c` files (definitions: the actual code) and `.h` headers (declarations: "a function with this name and these
parameters exists somewhere"). `#include "x.h"` pastes the header in. Each `.c` file is compiled separately into an *object file*; the
**linker** joins them. In this project all `src/*.c` become one **DLL** (dynamic-link library): a file other programs load at run time.
Functions marked `CANOPY_API` (really `__declspec(dllexport)`) are visible to the outside - that is the *public API*; everything else is
private. The tests are separate programs that compile the library's `.c` files directly, so they can also call private ("internal")
functions; Python can only call what the DLL exports.

### 3.2 Pointers

A **pointer** is a variable holding a memory address. `float *out` means "the address of a float (the first of possibly many)". Arrays
and buffers are passed as pointers. A span query takes `float *out` and `int64_t n`: "write n floats starting at that address".
Two classic dangers: reading/writing *outside* the memory you own (a *buffer overflow*), and using memory after it was freed (a
*use-after-free*). C does not stop you; the program may crash, or silently misbehave. This is why so much of this project's testing is
about catching exactly these.

### 3.3 Manual memory management

There is no garbage collector. You ask for memory (`malloc`/`calloc`), and you must give it back (`free`) exactly once. Forgetting is a
**leak**; doing it twice or too early is a **double free** / use-after-free. Project rule: *every* allocation in `src/` goes through our
wrappers `canopy_alloc`, `canopy_realloc`, `canopy_free` (or a **pool**, which collects many small blocks so they are all freed together
- convenient when building a structure out of many pieces that might fail halfway). Why wrappers? Because they let the tests (a) **count
live blocks**, so any leak shows up as a number that doesn't return to its starting value, and (b) **make the Nth allocation fail on
purpose**, so every "out of memory" path gets exercised. Without that, out-of-memory code is never run and therefore never trusted.

### 3.4 Structs, and "opaque" handles

A `struct` groups fields. Public headers often declare `typedef struct CanopyEngine CanopyEngine;` without saying what is inside: an
**opaque type**. Callers can only hold a pointer to it and pass it to our functions; they cannot reach into it. This is how the DLL
keeps its internals private (`canopy_core.h` has the real structs; it is not part of the public API).

### 3.5 Function pointers and callbacks

A **function pointer** holds the address of a function, so code can call "whatever function I was given". A node type is described by a
struct that includes pointers to its handlers (`query_at`, `query_span`, `on_action`, ...). The engine calls those without knowing what
they do. A **callback** is a function you hand to a library so *it* can call *you* later. miniaudio calls our "fill" callback whenever
the sound card wants more audio.

### 3.6 Integers of exact size, and overflow

`int64_t` is exactly 64 bits, signed. Arithmetic on signed integers that exceeds the range is **undefined behaviour** in C (anything may
happen). Time maths here multiplies nanoseconds by sample rates, which can overflow, so the code splits times into whole seconds and
remainder first, and has explicit overflow checks (the design mandates "no 128-bit integers", because MSVC has none).

### 3.7 `const`, `static`, and scope

`static` on a function or global means "private to this file". `const` means "not modified through this pointer". They document
intent and let the compiler catch mistakes.

### 3.8 Compiler flags we use, and why

`/W4 /WX` = nearly all warnings, and warnings are errors (an unused variable stops the build). `/std:c11` = the C11 standard.
`/experimental:c11atomics` = MSVC's support for C11 atomics (section 4). `/fp:precise` = floating point must behave identically every
run. `/utf-8` = source files are UTF-8.

### 3.9 Tools that find memory bugs (we use all of these)

- **Debug heap** (MSVC debug C runtime): checks the whole heap on every allocation/free, so a write past the end of a block is caught
  immediately, and it lists leaked blocks at exit.
- **AddressSanitizer (ASan)**: the compiler instruments loads and stores; any out-of-bounds access or use-after-free aborts with a
  report naming the line. Slower, but very thorough.
- **Our own live-block counter** (above).

### 3.10 Text encoding and line endings

Project text files use Windows line endings (CRLF). The vendored headers (`dr_wav.h`, `miniaudio.h`) stay byte-for-byte as downloaded
(LF) so their checksums prove they are unmodified. A script checks all 70 text files; last run: 0 problems.

---

## 4. A concurrency primer

CANOPY is fundamentally a *concurrent* program: several threads touch the same data at the same time. Almost every difficult decision
in the project comes from that. Here are the ideas, in the order they build on each other.

### 4.1 Threads, and why there are several

A **thread** is an independent flow of execution inside one process; all threads share the same memory. In a CANOPY-using program you
may have: the **UI thread** (tkinter, editing the graph); one or more **worker threads** rendering video frames and asking for
audio-derived values; and, when the preview plays, an **audio thread** owned by the sound system that wakes up every ~20 ms to ask
"give me the next 960 samples".

### 4.2 Data races, and why they are the enemy

A **data race** happens when two threads access the same memory location, at least one writes, and nothing orders them. In C this is
undefined behaviour. Typical symptoms: torn values, stale values, crashes that appear once a month. You cannot make them reliably
reproducible, which is why this project prefers *designs that make races impossible* over tests that merely hope to see them.

### 4.3 Atomics

An **atomic** variable supports operations that happen indivisibly: another thread sees the old value or the new one, never half.
Examples used here: `atomic_int playing` (is the preview playing?), `atomic_llong position` (which audio frame is next).
Operations: *load*, *store*, *fetch-add*, *exchange*, and **compare-and-exchange (CAS)**: "set this to NEW only if it still equals
OLD; tell me whether it worked". CAS is how you do "update unless someone else changed it meanwhile". The preview uses it so that when
the user types a new time *while* an audio callback is finishing, the typed time **wins** instead of being overwritten by the
callback's "advance by n frames".

### 4.4 Memory ordering (the part that surprises everyone)

Modern CPUs and compilers reorder memory operations. Another thread may see your writes in a different order than you wrote them.
**Memory-order** arguments on atomic operations say how much ordering you require:

- **relaxed**: only atomicity, no ordering with other variables.
- **release** (on a store) / **acquire** (on a load): if thread B's acquire-load sees the value thread A wrote with a release-store,
  then B also sees everything A wrote *before* that store. This is how one thread "publishes" a fully built object to another.
- **seq_cst** (sequentially consistent): the strongest; all such operations appear in one global order. Used where two threads
  must agree on who went first (the epoch mechanism, 5.9).

On x86-64 (the only CPU family tested here) many of these are cheap or equivalent; on ARM they differ. That's why the project says the
ordering is *believed* correct on other CPUs, not verified.

### 4.5 Locks (mutexes)

A **lock** lets one thread at a time into a region of code. Others **block** (sleep) until it is released. We use the Windows **SRW lock**
("slim reader/writer"), which has two modes:

- **shared** (reader): many threads may hold it at once, provided nobody holds it exclusively. Used for operations that only *read*
  the engine's lists (knob writes, counts, button presses).
- **exclusive** (writer): only one holder, and no shared holders at the same time. Used for operations that *change* the lists
  (installing a graph, making/freeing instances, collecting garbage).

Costs/dangers: a held lock stalls everyone who wants it; if A waits for a lock B holds while B waits for one A holds, both wait forever
- a **deadlock**. SRW locks are also **not recursive**: taking an exclusive lock you already hold deadlocks.

### 4.6 Why the audio thread must never wait

The sound card needs its next 960 samples *on time*. If the audio thread blocks on a lock (say the UI thread is mid-install), or calls
`malloc` (which may take a lock internally, or ask the OS for memory), it can miss the deadline and you hear a dropout (a click or gap).
Worse: **priority inversion** - the audio thread (high priority) waits for a low-priority thread that holds the lock but isn't getting
CPU. So the rule for code that runs on the audio thread - **realtime-safe** code - is: *no locks, no allocation, no I/O, bounded time*.
In CANOPY: **queries take no lock and allocate nothing**. This rule shapes the whole architecture, and the tests *check* it (a test holds
the engine's locks itself and shows that the audio callback keeps being called; another counts allocations while it plays).

### 4.7 Lock-free designs: "publish by swapping a pointer"

If readers may never lock, how does a writer change shared data? The standard trick: the writer prepares a complete **new** version
off to the side, then makes it visible with one atomic pointer swap (a release-store). Readers pick up the new version the next time
they look (an acquire-load). They never see a half-built object. CANOPY uses this for new graphs (5.7) and for replaced WAV data (5.9).

### 4.8 The reclamation problem

After publishing the new version, the writer wants to free the **old** one. But a reader may *still be using it*. Freeing it now is a
use-after-free. You must wait until no reader can possibly still hold it. Techniques: reference counts; **epochs** (what CANOPY uses,
5.9); hazard pointers. This is the hardest problem in the project, and the source of the "idle instances retain old graphs" limit in
section 11.

### 4.9 Per-thread state ("instances")

Another way to avoid sharing: give each thread its own copy of whatever is mutable. CANOPY calls this an **instance**: "one thread's
engine over a compiled graph". Filter memory, scratch buffers and the like are per instance, so nodes need no locks. The compiled graph
itself is **immutable** (never changed after being built), so many instances can read it simultaneously with no synchronisation at all.

### 4.10 Testing concurrent code

Two rules adopted here after real mistakes: (1) a thread test must be **paced by the other threads' progress**, never by sleeping and
hoping ("wait until each reader has answered at least once between installs"), otherwise it passes just because the readers got no CPU;
(2) a test must **always stop its threads** (in a `finally`/cleanup), otherwise a failed assertion leaves threads running and hangs the
whole run. The test runner also kills any C test program that runs >180 s and any Python test >30 s, so a deadlock fails instead of
hanging.

---

## 5. The architecture, from the bottom up

### 5.1 The life of a graph (the big picture)

```
 host builds a                 compile                    install
 GRAPH DESCRIPTION  ---->  COMPILED GRAPH  ---->  becomes the engine's "current" graph
 (plain data: nodes,       (immutable, checked,          |
  settings, knobs,          sorted, with extras)          |  each INSTANCE adopts it
  connections)                                            v  at the start of its next query
                                                    thread's INSTANCE answers queries
```

1. **Description** (`CanopyGraph`): just data. `canopy_graph_add_node(g, 7, "file_read")`, `canopy_graph_set_string(g, 7, "path", ...)`,
   `canopy_graph_connect(g, 7, "left", 9, "in")`. Nothing is validated yet. Used by one thread.
2. **Compile**: checks everything (unknown node types, duplicate IDs, unknown settings, a setting of the wrong kind, two connections into
   one inlet, duplicate boundary names...). Any fault is a clear error message and **nothing changes** (the old graph keeps running).
3. **Install** (`canopy_engine_set_graph`): a *transaction* - either the whole new graph becomes current, or (if memory runs out) the
   engine is exactly as before. 
4. **Instances** adopt the new graph without ever being stopped (5.7).

### 5.2 Node types: descriptor, registry, handlers

A **node type** (e.g. `file_read`) is described by one struct, `CanopyNodeType`: a permanent key, a display name, flags, a list of
**inlets** (inputs, each with a default knob position), **outlets** (outputs), **settings** (saved values: int, float, string, path,
choice), **widgets** (UI controls declared as *data* so the editor can draw them), the number of **scratch buffers** it needs, and
**handlers** (function pointers). The **registry** holds all registered types and checks each descriptor thoroughly when registered
(bad keys, duplicate ports, a choice default out of range...).

Key rules: built-in keys are plain (`file_read`); every third-party key must contain a dot (`vendor.name`) so they can't collide.
Some **flags are built-in only** and refused for third parties: the boundary flags and (new in step 7) `CANOPY_FLAG_SERVICE`.

**Handlers:**

| Handler | When | Notes |
|---|---|---|
| `create_shared` / `destroy_shared` | once per node ID (not per instance) | for things like the loaded WAV data or the audio device |
| `create_instance` / `destroy_instance` | once per instance | per-thread state (filter memory...) |
| `query_at`, `query_span` | when asked | **run on the querying thread**; no allocation/locks allowed in realtime-safe nodes |
| `on_action` | a UI button was pressed | runs on the calling (UI) thread |

A node implements `query_at`, `query_span`, or both. If it has only the point one, the engine derives spans by calling it once per
sample time; if only the span one, a point query asks for a 1-sample span. 

### 5.3 The context (`CanopyCtx`)

Every handler receives a `ctx`: "this node, in this instance, during this call" (valid only until the handler returns, never used from
another thread). Through it a node can: query its inlets (`canopy_inlet_at`, `canopy_inlet_span`) - if an inlet has no connection it
transparently returns the **knob** value, so a node never branches on "is it connected?"; borrow **scratch** memory
(`canopy_scratch`); read its settings (`canopy_ctx_int/float/string`); get its shared resource and instance state; read an
**upstream stamp** (5.6); announce a shared-resource change; retire old data (5.9); set a message (5.10).

### 5.4 Span placement and errors

Sample `i` of a span `[t0, t1)` with `n` samples is at `t0 + floor(i * (t1 - t0) / n)`; computed as `t0 + i*q + floor(i*r/n)` with
`q, r` = the quotient and remainder of `(t1 - t0)` divided by `n`, to avoid overflow. Reversed spans (`t1 < t0`) play backwards; `n`
must be 1 to 65536. On any failure the callee **zero-fills the whole output buffer** - so a caller never reads leftover garbage. These
rules are verified against independent big-integer arithmetic in Python.

### 5.5 The scratch arena

Nodes sometimes need temporary buffers during a query. Allocating in the query path is forbidden, so each instance owns an **arena**: a
block allocated once (when the instance or graph is created) from which `canopy_scratch(ctx, n)` hands out pieces, which are reclaimed
automatically when the handler returns. Each node type declares how many buffers it holds *at once*; the compiler works out the
deepest chain of nested queries to size the arena so it can never run out for a loop-free graph.

### 5.6 Knobs, slots and generation numbers ("how do stateful nodes know something changed?")

Every inlet has a **knob**: a float in -1..1 stored in a **slot** = an atomic float + an atomic **generation number**. Writing a knob
stores the value *first*, then bumps the generation. A reader reads generation first, value second - so it can only ever see a value
that is *newer than or equal to* its generation, never older; at worst a cached result is thrown away needlessly, never kept wrongly.

Nodes that keep history (filters, envelope followers) cache **checkpoints** of their state. The design says staleness is detected by
*pulling*, not by notification: at the start of a query, a node asks for `canopy_ctx_upstream_stamp(ctx)`: a 64-bit digest of the
generation numbers of **everything upstream** of it (knobs of unconnected inlets, boundary values, settings, shared resources, and the
wiring). If the digest differs from the one its checkpoints were made under, it discards them. Nothing is broadcast; no registry of
listeners exists. (Two different sets of numbers could in theory give the same digest - probability about 2^-64.)

### 5.7 Compile-and-swap: changing the graph while queries are running

This is the heart of "live editing during playback".

- The installing thread (UI) builds, for **every live instance**, a **package**: everything that instance needs to run the new graph -
  its new table of node states, fresh state for any new node, a bigger scratch arena if needed. All allocation happens *here*, on the
  UI thread.
- The package is linked onto the instance's list with a **release-store**. The instance, at the start of its next query, does an
  **acquire-load**, finds it, and applies it with *pointer swaps only* (no allocation, no lock). It then marks the package `done`
  (release), after which the UI thread may free what the instance finished with.
- State is **carried over** for a node that exists in both graphs (same node ID and same node type), so a filter keeps ringing
  correctly while you change something elsewhere. A node that disappears has its state destroyed later by the UI thread.
- **Records:** things that must outlive any single compiled graph (knob slots, boundary values, shared resources, setting generations)
  live in a per-(node ID, type) **record** owned by the engine. Node IDs are never reused within a graph.

Consequence (a *known limit*): an instance that never queries never adopts, so it keeps every graph installed since its last query
alive. Fixing this from the engine side would let two threads touch one instance, which could make a realtime query fail with `BUSY`;
that trade was declined.

### 5.8 The engine's lock - exact rules

| Takes it **exclusively** | Takes it **shared** | Never takes it |
|---|---|---|
| install a graph; make an instance; free an instance; collect; free the engine; **(new) the buttons of a preview node** | set/get knob; write boundary value; list boundaries; node count; graph serial; node message; ordinary node buttons; the preview's state/set-time/warning calls | **queries** (point and span), from any thread |

Handlers `create_shared`, `destroy_shared`, `create_instance`, `destroy_instance` run with the lock held. A slow one delays installs and
knob writes - never queries.

### 5.9 Retiring replaced data (epochs)

Problem (4.8): the file node replaces its WAV samples when you press "open" again. Queries may be reading the old samples right now.

Solution, with **no locks in the query path**:

1. Each instance has an **epoch** counter. A host-style query increments it on entry (making it *odd*) and again on exit (*even*).
   Both increments are `seq_cst`.
2. The writer swaps in the new data with an atomic exchange, then calls `canopy_ctx_retire(ctx, old_block, release_fn)`.
3. Retire looks at every instance's epoch. An instance with an *odd* epoch is mid-query and might hold the old block; retire records
   "wait until instance X's epoch changes". Instances with even epochs cannot hold it (their next query will read the *new* pointer,
   thanks to seq_cst ordering).
4. When every recorded instance has left its query, the block is freed - by the UI thread during the next install/collect/instance-free.
5. If even the bookkeeping allocation fails (out of memory), the writer waits (spins) for the running queries itself: never leak,
   never free early.

Cost measured: two extra atomic increments per host query; the difference from not having them was inside the noise (<1 ns).

### 5.10 Node messages

A node can say something about itself ("file not found: ...", "audio device not found..."). Stored in a **fixed 256-byte buffer inside
the node's record** (cut at a UTF-8 character boundary), protected by a tiny `message_lock`. Fixed size because a message must be
storable *when memory has run out* - exactly when a node most needs to say "out of memory". Read by the host with
`canopy_engine_node_message`.

---

## 6. The three built-in nodes

### 6.1 Boundary nodes (step 5): the door between host and graph

- `boundary_inlet`: the **host writes** a float by name (`canopy_engine_set_boundary(engine, "intensity", 0.7f)`); inside the graph that
  value is what its outlet returns for any time. An atomic store; accepts any float (NaN, infinity, huge: nothing is clamped).
- `boundary_outlet`: the **host reads** through it by name, using point or span queries.
- Names are non-empty and unique across both kinds (compile fault otherwise); sorted by name so lookup is a binary search; the value
  belongs to the node (rename it and the value stays). This is how light_bounces will read audio-derived numbers.

### 6.2 `file_read` (step 6): WAV files

Uses **dr_wav** (vendored; allocation redirected through `canopy_alloc`). Accepts PCM 8/16/24/32-bit and 32-bit float. Mono feeds both
outlets (`left`, `right`); more than two channels uses the first two. Frame k sits at k / sample_rate seconds from t = 0; between
frames the value is **linearly interpolated**; before the first frame and after the last it is silence. Loaded when the node first
appears in an installed graph and when the action `"open"` is pressed - *not* when a later graph names a different path. A failed load
keeps the old file and puts a message on the node. New data replaces old by atomic swap + epoch retiring (5.9).

### 6.3 `realtime_preview` (step 7): see section 7.

---

## 7. Step 7 in depth: sound to a real device

### 7.1 What the design asked for

A node that plays the graph to a sound device in real time; it is the **only** place a playback state exists. Play and Pause buttons,
a typed time, a device choice saved by name (default device if missing), 48000 Hz, requests to the graph in chunks of at most 65536,
three inlets - left, right, center - mixed as left+center and right+center with clipping, silence after the end of the audio, and a
warning (not a refusal) for nodes not flagged `realtime_safe`.

### 7.2 miniaudio and the null backend

**miniaudio** is a single-header C library that talks to sound hardware (we use its Windows backend, **WASAPI**). We compile only device
I/O, and only two backends: WASAPI and its **null backend** - a fake device that takes audio at real-time speed and throws it away,
which lets every test run without sound hardware (the design demands this). `src/canopy_audio.c` is the only file that includes it; it
wraps miniaudio in a tiny API (open a device by name / list devices / close). Details that matter:

- miniaudio says creating/destroying contexts and devices is **not thread-safe**, so every such call sits behind one process-wide lock.
- All its memory goes through our counted allocator. Its callbacks don't tell us the old size on resize, so each block carries a 16-byte
  header with its size (and the header keeps 16-byte alignment).
- *Finding:* miniaudio itself **leaks** when one of its allocations fails inside `ma_device_init` (its cleanup returns early for a
  half-built device; with the null backend a helper thread stays alive too). So the tests' "fail the Nth allocation" hook is deliberately
  *not* applied to miniaudio's allocations (`canopy_alloc_unhooked`: counted, but never failed). Everything of *ours* around it is
  still swept.

### 7.3 The audio callback

miniaudio calls our `fill(user, stereo, frames)` from **its own thread** whenever the device wants audio (960 frames every 20 ms in our
configuration; three such periods are buffered, ~60 ms). `fill` does, for each chunk of at most 65536 frames:

1. read `playing` and `position` (atomics); if paused, write silence and don't advance;
2. convert frame numbers to times: `t0 = ns(position)`, `t1 = ns(position + n)` - exact frame boundaries, so consecutive callbacks
   **tile** with no gap or overlap;
3. ask the graph three times (left, right, center inlets) with span queries through the node's **own instance** (7.4);
4. write `clip(left + center)` and `clip(right + center)` interleaved; `clip` limits to [-1, 1]; **NaN becomes 0** (not a full-scale
   click); a failing inlet is silence for that channel;
5. advance `position` by n using **compare-and-exchange**: if the user seeked meanwhile, the CAS fails and the seek stands.

If the preview node is not in the graph that the audio thread's instance currently runs (it was deleted), output is silence and
the position stands still. It allocates nothing and takes no locks; this is *checked*, not just claimed.

The position is a **frame count at 48 000 Hz**, which makes every whole millisecond exact (48 frames) - so the hh:mm:ss.mmm text field
round-trips perfectly. Typed times are rounded half-up to a frame.

### 7.4 The problem of the audio thread's instance, and the "service instance"

The design says each querying thread uses its own instance. The audio thread is a querying thread, so it needs one. But:

- `canopy_engine_new_instance` takes the engine lock **exclusively**; button handlers (`on_action`) used to run under the lock
  **shared**; the lock is not recursive and cannot be upgraded; and `create_shared` runs during an install, possibly the very first one,
  when there is no installed graph yet to base an instance on.

The solution adopted (choice 4, examined in section 12): the engine can create a **service instance** - an instance made *for one of
its own nodes* (marked `CANOPY_FLAG_SERVICE`, built-in only). It is in the engine's instance list, so installs prepare it like any
other. `canopy_engine_free` doesn't count it as the host's (otherwise the engine could never be freed), and stops such nodes' devices
**first**, while every graph they might refer to still exists. Created lazily at the first Play; freed when the device closes.

### 7.5 What each button does

- **play**: if a device is open for a different `device` setting (or it stopped by itself) close it; if none is open, open one (making
  the instance and buffers, starting miniaudio); set `playing = 1`.
- **pause**: `playing = 0`. The device stays open and plays silence (so edits keep being adopted and Play answers within a period).
- **device**: if a device is open and the setting now names another one, switch, keeping the playing/paused state.

Failures never throw: the button leaves the node paused and puts the reason in the node's message ("cannot play: ...", "out of memory",
"audio device not found: X; using the system default"). A device that stops by itself (e.g. unplugged) pauses the node and says so.

### 7.6 What the editor can call (all exported)

| Call | Purpose |
|---|---|
| `canopy_engine_action(engine, id, "play"/"pause"/"device")` | the buttons |
| `canopy_preview_state(engine, id, &playing, &time_ns)` | poll to show the time |
| `canopy_preview_set_time(engine, id, ns)` | the typed time |
| `canopy_engine_audio_devices(engine, buf, cap, &len)` | device names, newline-separated |
| `canopy_preview_warning(engine, id, buf, cap, &len)` | the not-realtime-safe text |
| `canopy_engine_set_audio_backend(engine, SYSTEM or NULL)` | choose the null backend for tests |

Buffer-returning calls use one convention: copy as much as fits (NUL-terminated), report the **full length**, so you can ask again with a
big enough buffer. Because a `CHOICE` widget is declared as fixed data, the device list can't be inside the descriptor; the descriptor has
one fixed entry "(system default)" and the editor adds the real names (your decision at step 7).

### 7.7 Verified with the real device (silence only)

Play took 12-17 ms; over 1.000 s of wall time the preview time advanced exactly 1.000 s; Pause held it still; closing took 50-60 ms;
nothing leaked; it works even when the calling thread has COM initialised as a single-threaded apartment (some GUI programs do).
Your machine's only output device is "LG TV SSCR2 (NVIDIA High Definition Audio)".

---

## 8. How the project is tested (and why the tests are shaped this way)

### 8.1 Philosophy

Tests are written **before** the code where a contract is precise (time maths, statuses, determinism); they compare against
**independent references** (big integers in Python, plain-formula C, a model of WAV decoding written in the test); they are never
loosened to pass - when a test fails, first suspect the test, then check which it really was. Every bug fix gets a regression test.

### 8.2 Three runs of every C test

`python run_tests.py` builds the DLL and three C test programs and runs the **same** 219 C tests: normal (optimised), against the MSVC
debug heap, and under AddressSanitizer; then 45 Python tests through ctypes. One total is printed; any failure, leak, or sanitizer report
in any run counts as a failure.

### 8.3 Leak and out-of-memory tests

A `Rig` (test helper) builds registry, graph, engine and instance and, at close, checks that the live-block counter returned to its
starting value. "Out-of-memory sweeps" make allocation #0, #1, #2... fail in turn through `canopy_alloc_fail_after(n)` ("everything
after n fails") and require: clean error, no change to engine state, no leak. Step 7 added `canopy_alloc_fail_once(n)` ("exactly the
nth fails") - needed to reach code that copes with *one* failed allocation (a node whose shared resource couldn't be made).

### 8.4 Test hooks (internal, not exported)

To test things that can't be forced naturally: `canopy_audio_force_failure(stage)` (pretend miniaudio failed at stage 1-5),
`canopy_audio_stop_for_test` (pretend a device was unplugged), `canopy_preview_fill/prepare/counts/...` (run the audio thread's work
directly with exact references), `canopy_engine_test_action_window(hook)` (run code in the exact moment between a button letting go
of the shared lock and taking the exclusive one - where a real install from another thread could slip in).

### 8.5 Mutation testing

"If I break the code on purpose, do the tests notice?" `dev/mutation/mutate.py` applies one small deliberate fault at a time (e.g. change
`<` to `<=`, remove a free, drop a lock), runs the entire suite, and reports **caught** (some test failed or the program crashed),
**SURVIVED** (suite stayed green: a weak test or an equivalent mutation) or **BUILD FAILED**. Totals now: step 3: 83, step 4: 134,
step 5: 53, step 6: 64, step 7: 142 - all caught. Survivors found in step 7 led directly to new tests (for example, nothing tested the
message for a device that cannot be opened, because the null backend never fails - hence the forced-failure hook). One mutation was
judged *equivalent* (provably can't change behaviour) and dropped, with the reasoning written in the spec.

### 8.6 Real-time tests without flakiness

Tests that open the null device wait on **progress** (the audio callback counter, the preview time), with generous deadlines only to
end a failing run. Stability checked: the C program 12 times on an idle machine and 6 times with 24 busy processes on 12 cores:
no failures.

### 8.7 What tests deliberately never do

They never open the machine's **real** audio device (they select the null backend); a bug or mutation that routed them to the real
one would play test signals on your speakers. Mutation specs avoid such mutations.

---

## 9. Build, files and conventions

**Commands:** `python run_tests.py` (build + everything); `python run_tests.py --no-build`; `-k text`; `python
dev/mutation/mutate.py dev/mutation/step7.py`; `python dev/listen_check.py --list`.

**Layout (abridged):**

- `src/canopy_alloc.c` counted allocation + pool; `canopy_time.c` the public time helpers; `canopy_registry.c` descriptor checks;
  `canopy_graph.c` graph descriptions; `canopy_engine.c` compile + host calls; `canopy_install.c` records, generation numbers, install
  transaction, reclaim; `canopy_package.c` instances and packages; `canopy_instance.c` queries and context calls;
  `canopy_retire.c` epochs + messages; `canopy_boundary.c`, `canopy_fileread.c`, `canopy_preview.c` the built-in nodes;
  `canopy_audio.c` miniaudio wrapper; `canopy_test_nodes.c` the hidden stateful test node (`test_filter`).
- Headers: `canopy.h` (statuses, time helpers), `canopy_node.h` (what a node author uses), `canopy_engine.h` (what a host uses),
  `canopy_core.h` / `canopy_internal.h` / `canopy_audio.h` (private).
- `third_party/` unmodified vendored headers with hashes in its README. `tests/c`, `tests/python`, `dev/`, `docs/`, `build/` (generated).

**Conventions:** Windows/MSVC only for version 1; CRLF everywhere except vendored headers; the **build number** (`CANOPYSYNTH_BUILD`,
now 8) is bumped once per finished prompt that changed code and must match in `src/canopy.h` and `canopysynth/version.py` (the DLL
exports it and the Python loader refuses a mismatch); no numpy dependency; no git yet.

**Rules R1-R10** (in the plan): the design is law; tests first; run the full suite after every edit; say verified vs believed;
no design drift; end every report with next step + effort level; Windows specifics; deterministic floats; minimal dependencies;
never delete your files.

**Tooling gotchas learned the hard way:** shell heredocs mangle backslashes (a `'\0'` became a real NUL byte in source files three
times; repaired and now documented), so scripts with backslashes go through the Edit/Write tools; `sed -i` can strip CRs.

---

## 10. Measurements (all with throwaway programs, optimised build)

| What | Result |
|---|---|
| host query of a bare inlet | ~5-6 ns (the epoch counters cost <1 ns, inside noise) |
| loading a 10 s stereo float WAV (3.8 MB) | 5.5 ms; re-"open" 1.4 ms |
| file span, 512 samples at the file's density | ~4.8 ns per sample |
| one preview callback (960 frames = 20 ms period), inlets as knobs | ~0.9 us |
| ... with a stereo float file on left and right | ~10 us (0.05% of the 20 ms budget) |
| ... ten gain nodes in a row | ~1.9 us |
| Play, null backend | ~1.6 ms (first time ~4 ms); Pause 0.3 us |
| Play, real WASAPI device (silence) | 12-17 ms; closing engine 50-60 ms |
| "device" switch (close + open), real / null | 63-73 ms / 21-33 ms of exclusive lock; worst stall seen by a 1 kHz boundary writer: 58 ms / 33 ms |
| DLL size | 260 KB -> 428 KB (miniaudio) |

Caveat stated at the time: the first version of the file-callback measurement was wrong twice (a relative path made the file node
refuse to load; then the preview had run past the end of the 10 s file) - both noticed because the output peak printed as 0.000, and
fixed before any number was recorded. Callback cost with *heavy* nodes is unmeasured: no heavy node exists yet.

---

## 11. Known limits, and what is only believed

**Known limits (documented in the plan):**
- *Idle instances retain graphs* installed since their last query (a stopped preview device is such a case).
- Handlers run under the engine's lock, so a very slow one (a huge file load) delays installs and knob writes.
- A chain of N nodes costs O(N^2) memory/time at install for the per-node "what is upstream" lists (fine for tens of nodes).
- A deleted preview node's device closes only at the next install or `canopy_engine_collect`.
- Opening a device is synchronous: a hanging driver would freeze the calling thread (the UI).
- `file_read` doesn't reload when a later graph changes its path; the editor must send "open".

**Believed, not verified:** what you will *hear*; WASAPI behaviour on unplug, with other devices, or against another program's exclusive
mode; other COM apartment types; the "out of memory" mapping for a real miniaudio allocation failure (tests can't trigger it); memory
ordering on non-x64 CPUs; behaviour of a heavy graph in the audio thread; dr_wav against hostile files (not fuzzed).

---

## 12. Three choices examined: 4, 6 and 7

These are items 4, 6 and 7 of the "choices of mine you can veto" list in the step 7 report. For each: what I did, why, the alternatives,
pros and cons, and my honest opinion with a confidence level.

### 12.1 Choice 4 - the preview's buttons take the engine's lock exclusively

**What it is.** Normally a button press (`canopy_engine_action`) takes the engine lock *shared*, so it runs alongside knob writes and
other presses and only waits for installs. For a node flagged `CANOPY_FLAG_SERVICE` (only the preview), `canopy_engine_action` does:
take shared -> find node -> see the flag -> **let go** -> take **exclusive** -> **look the node up again** -> run the handler -> release.
The re-lookup is essential: between letting go and re-acquiring, another thread's install may have replaced the graph (and freed the
old one), so the first node pointer may be dangling. A test hook runs an install *exactly in that window* to prove the re-lookup works
(removing the re-lookup is a mutation that tests catch).

**Why it was needed.** Creating and freeing the audio thread's instance modifies the engine's instance list and reads the current graph;
the design's contract is that such operations hold the lock exclusively. A shared holder cannot upgrade to exclusive (deadlock), so the
choice was: make *this* kind of button exclusive from the start.

**Cost.** While a button that opens or closes a device runs, installs, knob writes and boundary writes from other threads wait. Queries
never wait. Measured afterwards (the step 7 report only quoted the Play figure, which understated it): a Play on a closed device holds the
lock 12-17 ms with the real device; a "device" switch (close the running device, open another) holds it 63-73 ms on the real device and
21-33 ms on the null backend, because closing waits for the device's thread to finish its period. A thread writing a boundary value every
millisecond saw single calls stall up to 58 ms (real) / 33 ms (null) during such presses: for a render loop at 60 frames per second, a
hitch of up to about four frames when the user presses the button. Never a crash and never a wrong value; a delay.

**Alternatives.**

| # | Alternative | Pros | Cons |
|---|---|---|---|
| A | **Chosen:** exclusive lock for service-flagged nodes only | Small code change; one clear rule; every preview state change (open, close, switch, destroy) serialised with installs and each other, so little room for races; ordinary nodes keep shared behaviour | Knob/boundary writes stall during a device open; a hung driver would freeze the UI thread *and* hold the lock; adds a node-type flag and a special path in `canopy_engine_action` |
| B | Make **all** actions exclusive | Simplest rule, no flag, no upgrade/re-lookup dance | Slows every node: a 1 GB WAV "open" (~1.5 s) would block every knob/boundary write for its duration; changes a deliberately chosen contract for all nodes |
| C | Create the instance **eagerly at install** (inside `create_shared`, already exclusive) | Play becomes fast and lock-light | First install has no graph to base an instance on; install is a transaction so rollback must also undo the instance; an idle instance holds back every old graph from the moment the node appears (unbounded growth during editing unless the installer adopts on its behalf, which risks spurious `BUSY` on a realtime query) |
| D | **Host/Python creates** the instance and hands it to the C node | No engine special cases; each side owns what it creates | Pushes lifecycle onto every host (forgetting to free it makes `engine_free` return BUSY); the "C library owns the device" intent weakens; every test/host must replicate it |
| E | A **control thread** per preview does the slow work (open device, create instance) asynchronously | UI never blocks; hung drivers can't freeze the editor; no long exclusive hold | Asynchronous results (tests must wait; errors arrive later); threads must be joined during `destroy_shared` while the engine lock is held - the control thread may itself be waiting for that lock = deadlock unless try-locks/timeouts are added; more state machine, more bugs |
| F | **Two-phase**: make the instance under a brief exclusive hold, then run the handler (open the device) under *shared* | Slow part wouldn't block knob writes | Closing/switching also frees the instance (needs exclusive again); the handler can't safely assume the lock mode; ends up more complicated than A for little benefit given 15 ms |
| G | Move the slow `ma_device_open` **outside** any lock, pinning the node with a reference count | Shortest lock hold | Needs reference counting on records and a "being destroyed" protocol; precisely the type of subtle machinery that is hard to get right |

**My opinion.** A is the best trade for version 1 (confidence: fairly high, ~80%). The measured 15 ms stall is small compared with the
interactive cost of pressing a button, the scheme is easy to reason about, and it is covered by deterministic tests (the lock-mode
probe, the window hook, a thread test pressing buttons while another thread installs). What would make me revisit: (1) real drivers
that take hundreds of ms or hang - then E (or G) becomes attractive; (2) a host that writes boundary values from a render thread and
cannot tolerate a few ms of delay - a cheap mitigation is opening the device before taking the lock (a step towards G). The cheapest
undo is to delete the flag, which turns the preview back into an ordinary shared-lock node, but then it could not create its instance.

### 12.2 Choice 6 - the warning names only nodes that feed the preview, computed on demand

**What it is.** `canopy_preview_warning` walks backwards from the preview's inlets through the *installed* graph (loops handled),
collects every node reached, and lists those whose type lacks the `realtime_safe` flag, e.g. `not realtime safe, so the sound may break
up: test.gain (node 2), test.sum (node 5)`. Unrelated nodes in the same graph are not listed. It is a separate function; the node's
message string is not used for it.

**Why.** The design says "warns about graphs containing nodes not flagged `realtime_safe`". Those nodes are a problem only if the audio
thread *runs* them, i.e. they are upstream of the preview. Computing on demand means the text can never be stale after an edit.

**Alternatives.**

| # | Alternative | Pros | Cons |
|---|---|---|---|
| A | **Chosen:** upstream-only, on demand, separate call | Precise (no false alarms); never stale; no storage; loops safe; costs microseconds | A reading of the design that is narrower than its literal wording; the editor must call it after each install; an upstream node that is wired but never actually queried (e.g. gated off by another node) still triggers a warning (conservative) |
| B | **Whole graph**, literal reading | Matches the sentence exactly; trivial to implement | Warns about a Python/numba node used only for offline rendering that the preview never touches - noise that teaches users to ignore it |
| C | Compute at **Play** (or install) and store it in the node's **message** | One place to look in the UI; no extra API | Stale as soon as the graph is edited; the message is shared with device events (not found, stopped, out of memory), so they overwrite each other; message buffer is 255 bytes and cuts long lists |
| D | Warn **per node** in the editor (badge on each non-safe node), using the descriptor's `realtime_safe` bit the editor already has | Most helpful visually; no C code needed | Doesn't know which nodes actually feed the preview (so equals B's false alarms) unless the editor does the graph walk itself - duplicating logic in Python |
| E | **Refuse** to play such graphs | Guarantees glitch-free-ish playback | Forbidden by the design ("it does not refuse them") |
| F | Push notification (callback) when the warning changes | Editor needn't poll | Callbacks into Python from engine threads: more concurrency hazards; the pull model matches the project's "staleness is detected by pulling" principle |

**Notes on semantics worth knowing.** "Not flagged realtime-safe" includes every third-party node by default (authors must opt in), so
warnings are conservative by design. The preview excludes itself. The flag means "no allocation, no locks, no Python"; it is a *promise
by the author*, not something the engine verifies.

**My opinion.** A is the better *behaviour* and I'm confident in it (~85%), but it is an *interpretation*, which is why I flagged it. If
you want the literal reading, the change is small (skip the backward walk and list every non-safe node); a combined option is cheap:
return both, "upstream" and "elsewhere in the graph", and let the editor decide how loudly to show each.

### 12.3 Choice 7 - the tests rely on the null device's name in this miniaudio version

**What it is.** miniaudio's null backend reports exactly one playback device named `NULL Playback Device`. Several tests hard-code that
text: the audio-layer list test, the by-exact-name matching tests, the preview "device action" test, the device-list protocol tests,
and a Python test. A related check (the *system* list must not contain that name) depends on it as well.

**Why I did it.** It makes the tests *exact*: they assert what the list function actually returns, including exact-match semantics
(prefix and case variants must be rejected), without inventing a fake.

**The risk.** The name is miniaudio's choice, not ours. Upgrading `miniaudio.h` might rename it, and several tests would fail at once
- with a clear message, but for a reason unrelated to our code.

**Alternatives.**

| # | Alternative | Pros | Cons |
|---|---|---|---|
| A | **Chosen:** hard-code the string where needed; vendored version is pinned by size and SHA-256, so a change only happens by deliberate upgrade | Strongest assertions; zero extra machinery; failure is loud and points at the cause | Scattered literals (5+ places); upgrade day brings a round of mechanical edits; ties tests to a third party's wording |
| B | **One constant** (`NULL_DEVICE_NAME`) in a shared test header/Python module | Same strength; one edit on upgrade | Still wording-dependent; a small refactor of existing tests (not done yet) |
| C | **Discover** the name at run time: list the null backend and use the first entry | Immune to renaming | The list test becomes self-referential (it would pass for any non-empty name, so it no longer checks the list function), and "name must match exactly" tests need a derived "almost-name" (add a space, change case), which works but is subtler |
| D | Assert **structure only**: exactly one device, non-empty, no newline | Robust | Loses the exact-string check; the matching tests still need some name |
| E | A **custom miniaudio backend** (`ma_backend_custom`) we control, with names we choose | Complete control; could simulate multiple devices, unplugging, failures at will (removing the need for the forced-failure hook) | Substantial code (a mini fake backend); tests would exercise a different backend than the null one users of the library will rely on; much more to maintain |

**My opinion.** B is the cheapest improvement (do it at the next opportunity), possibly combined with C for the *matching* tests. E is the
most powerful but it is a project of its own, worth considering only if device-level simulation (multiple devices, unplug, rerouting)
becomes important. Confidence that A is acceptable for now: high (~85%), because the failure mode is loud and the version is pinned;
confidence that B is the right next tidy-up: ~70%. I did not make that change in step 7 because it was not requested and touching
many tests late in the step adds risk for little behavioural gain.

---

## 13. What is left to build

- **Step 8** - Python `Graph` model: add/connect/disconnect/remove, node IDs never reused, settings, knobs, boundary names, the loop
  check (`loop_protection`, saved), `to_dict/from_dict` (`format: "canopysynth-graph"`, version 1, permanent keys, migrations by type
  version); rejects an unknown node type; tolerates a missing WAV. Recommended effort: HIGH.
- **Step 9** - Python `Engine` / `Instance` over ctypes: version check, `value`, `audio` (a memoryview of float32), `set_boundary`,
  `boundary_nodes`, `QueryError`, `GraphError`, one instance per thread, GIL released during queries. The design's section 15 snippet
  must run as written.
- **Steps 10-12** - the tkinter editor: canvas, dragging nodes, drawing connections (fan-in impossible, loops refused by default),
  zoom/pan, knobs and widgets drawn from descriptor data, menus, then live editing and the preview controls (the calls in 7.6).
- **Step 13** - whole-system verification: determinism recordings, a multi-thread stress script, overrun checks, timings.
- **Step 14** - user documentation, node-author guide, packaging (the packaging question is still open).
- **Step 15** - audit of every design statement against what was built.

Pending from you: the listening check (`python dev/listen_check.py`).

---

## 14. Glossary

- **Acquire / release / seq_cst** - memory orderings for atomics (4.4).
- **Arena** - one big block from which temporary buffers are carved and released together (5.5).
- **ASan (AddressSanitizer)** - compiler instrumentation that aborts on memory errors (3.9).
- **Atomic** - a variable whose operations are indivisible (4.3).
- **Audio thread** - the sound system's thread that calls our fill function periodically (4.1, 7.3).
- **Backend (miniaudio)** - a way of reaching sound hardware: WASAPI (real) or null (fake) (7.2).
- **Boundary node** - a node through which the host writes to or reads from a graph (6.1).
- **Callback** - a function you give a library for it to call later (3.5).
- **CAS (compare-and-exchange)** - "set to NEW only if still OLD" (4.3).
- **Checkpoint** - cached state of a history-keeping node, valid for one upstream stamp (5.6).
- **Compile-and-swap** - build a new compiled graph, install it, let instances adopt it by pointer swap (5.7).
- **CRLF** - Windows line ending (3.10).
- **Data race** - unordered conflicting accesses from two threads; undefined behaviour (4.2).
- **Deadlock** - threads waiting for each other forever (4.5).
- **Descriptor** - the struct that fully describes a node type (5.2).
- **DLL** - a library loaded at run time; ours is `canopysynth.dll` (3.1).
- **Epoch** - per-instance counter, odd while a query runs, used to know when old data may be freed (5.9).
- **Equivalent mutation** - a deliberate code change that cannot alter behaviour, so no test could notice (8.5).
- **Exclusive / shared lock** - writer mode / reader mode of an SRW lock (4.5).
- **Generation number** - counter bumped each time a source of change is written (5.6).
- **Handler** - a function a node type provides for the engine to call (5.2).
- **Hook (test)** - a deliberate backdoor used only by tests (8.4).
- **Instance** - one thread's mutable engine state over a compiled graph (4.9).
- **Knob** - the per-inlet control that supplies a value when nothing is connected (5.6).
- **Lock-free** - designed so some threads never wait on locks (4.7).
- **Memory order** - how strictly an atomic operation orders surrounding memory accesses (4.4).
- **Mutation testing** - breaking the code deliberately to check that tests notice (8.5).
- **Null backend** - miniaudio's fake device used by tests (7.2).
- **Opaque type** - a type whose insides are hidden from users of the API (3.4).
- **Package** - everything an instance needs to move to a new graph, prepared by the installing thread (5.7).
- **Pool** - a set of allocations freed together (3.3).
- **Priority inversion** - a high-priority thread stuck waiting for a low-priority one (4.6).
- **Realtime-safe** - safe to run on the audio thread: no locks, no allocation, no I/O (4.6).
- **Record** - per (node ID, type) data that outlives any one compiled graph (5.7).
- **Registry** - the table of known node types (5.2).
- **Retire** - hand old data to be freed once no query can still see it (5.9).
- **Service instance** - an instance the engine makes for one of its own nodes (the preview) (7.4).
- **Shared resource** - one-per-node-ID data shared by all instances (loaded WAV, audio device, playback position) (5.2).
- **Slot** - an atomic float with a generation number (5.6).
- **SRW lock** - Windows slim reader/writer lock (4.5).
- **Span query / point query** - ask for n samples over [t0, t1) / ask for one value at t (1).
- **Stamp (upstream)** - 64-bit digest of the generation numbers of everything upstream of a node (5.6).
- **Tile** - consecutive blocks that meet exactly with no gap or overlap (7.3).
- **Undefined behaviour** - code the C standard gives no meaning; anything can happen (3.2, 3.6, 4.2).
- **Verified / believed** - ran-and-saw versus reasoned-but-not-run (page 1).
- **WASAPI** - Windows' audio API; miniaudio's backend for real devices (7.2).
