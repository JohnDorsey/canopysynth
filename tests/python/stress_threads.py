"""The Python-level multi-thread stress (plan step 13): what a host program does at once through the public API, with the real editor making the edits.
The main thread runs a Tk window with an Editor over a Graph and an Engine (audio on the null backend) and makes random edits through the editor (the
`random_edit_run` of test_editor_link.py, with all its checks after every edit), presses the preview's buttons and replaces the file the file node holds;
meanwhile other threads write a boundary inlet as fast as they can, read the boundary outlets it feeds through instances of their own (point queries and
spans), and ask the engine what it holds (boundary nodes, messages, the preview's state and warning). Every answer is checked without a lock:
  - the writer writes 1, 2, 3, ... to inlet "w" (whole numbers below 2^24, exact in a float32) and publishes a counter before and after each write; a reader of
    outlet "r" (wired to "w", never edited) must get a whole number from the window [writes completed before the query, writes started before its end], a span
    must be constant (one read of one boundary value), and what one reader gets never goes back (an install must never reset a boundary value);
  - the file node holds one of two files whose samples are all 0.25 or all 0.75, and is replaced and opened again meanwhile: outlet "fr" must give one of them,
    and never a mixture within a span;
  - no other thread may get an exception (the nodes they ask for are never edited), and the edits are never refused by the engine;
  - at the end every thread stops, the editor, the instances and the engine are closed, and nothing the engine allocated is left over.
The threads wait a fraction of a millisecond between two calls (a host's workers wait for work, and Tk, whose every call lets go of the GIL and takes it again,
starves for minutes among threads that spin in Python loops: that is the GIL's, not the library's; flat-out hammering is the C stress's job, which has no GIL).
A watchdog thread dumps the stack of every thread and ends the process if the main thread, or all the others together, move no more for 20 seconds.
`run` returns the counts."""
import faulthandler
import os
import random
import sys
import tempfile
import threading
import time

import engine_dll as e
from canopysynth import Engine, Graph
from test_editor import window
from test_editor_link import build, random_edit_run
from test_fileread import write_wav

WRITE_LIMIT = 16_000_000                       # whole numbers up to 2^24 are exact in a float32
PROBLEMS_SHOWN = 12


class Shared:
    def __init__(self):
        self.stop = threading.Event()
        self.intent = 0                        # the write the writer has started
        self.done = 0                          # the last write it has finished
        self.progress = 0                      # a heartbeat for the watchdog
        self.main_beat = time.time()           # and the main thread's own (the others can beat while it starves)
        self.problems = []
        self.counts = dict.fromkeys(("writes", "reads", "spans", "file_spans", "file_a", "file_b", "info_calls", "buttons", "opens", "collects", "edits"), 0)
        self.lock = threading.Lock()

    def problem(self, text):
        with self.lock:
            if len(self.problems) < PROBLEMS_SHOWN:
                self.problems.append(text)
        if len(self.problems) >= PROBLEMS_SHOWN:
            self.stop.set()

    def beat(self):
        self.progress += 1


def write_constant_wav(path, value):
    """A 16-bit mono file of one second at 8000 Hz whose every sample is `value` / 32768."""
    write_wav(path, 1, 16, 1, 8000, int(value).to_bytes(2, "little", signed=True) * 8000)


def writer(shared, engine):
    sequence = 0
    try:
        while not shared.stop.is_set():
            if sequence >= WRITE_LIMIT:
                time.sleep(0.01)
                shared.beat()
                continue
            sequence += 1
            shared.intent = sequence
            engine.set_boundary("w", float(sequence))
            shared.done = sequence
            shared.counts["writes"] += 1
            if sequence % 16 == 0:
                shared.beat()
            time.sleep(0.0003)
    except BaseException as error:                                                       # noqa: BLE001 - reported
        shared.problem(f"the writer: {type(error).__name__}: {error}")


def reader(shared, engine, seed):
    rng = random.Random(seed)
    try:
        with engine.new_instance() as instance:
            last = 0.0
            while not shared.stop.is_set():
                if rng.random() < 0.25:                                                  # the file
                    n = rng.choice([1, 16, 480])
                    values = list(instance.audio("fr", 10_000_000, 900_000_000, n))
                    shared.counts["file_spans"] += 1
                    if len(set(values)) != 1 or values[0] not in (0.25, 0.75):
                        shared.problem(f"outlet fr gave {sorted(set(values))[:4]} (n={n}): not one of the two files")
                    else:
                        shared.counts["file_a" if values[0] == 0.25 else "file_b"] += 1
                else:                                                                    # the counter
                    low = shared.done
                    if rng.random() < 0.4:
                        values = [instance.value("r", rng.randint(-10 ** 9, 10 ** 9))]
                        shared.counts["reads"] += 1
                    else:
                        values = list(instance.audio("r", rng.randint(-10 ** 9, 0), rng.randint(0, 10 ** 9), rng.choice([1, 7, 64, 960, 4096])))
                        shared.counts["spans"] += 1
                    high = shared.intent
                    value = values[0]
                    if len(set(values)) != 1:
                        shared.problem(f"a span of r held {len(set(values))} different values: a mixture of writes")
                    elif not (low <= value <= high) or value != int(value):
                        shared.problem(f"r gave {value!r} when the writes completed were {low} and the writes started {high}")
                    elif value < last:
                        shared.problem(f"r went back from {last} to {value}: an install lost a boundary value")
                    last = max(last, value)
                shared.beat()
                time.sleep(0.0005 * rng.random())
    except BaseException as error:                                                       # noqa: BLE001
        shared.problem(f"a reader: {type(error).__name__}: {error}")


def info(shared, engine, preview, file_node):
    try:
        while not shared.stop.is_set():
            names = {(b.name, b.kind) for b in engine.boundary_nodes()}
            if not {("w", "inlet"), ("r", "outlet"), ("fr", "outlet")} <= names:
                shared.problem(f"the engine's boundary nodes lack one of the protected ones: {sorted(names)}")
            playing, time_ns = engine.preview_state(preview.id)
            engine.preview_warning(preview.id)
            engine.node_message(file_node.id)
            engine.node_message(preview.id)
            if not isinstance(playing, bool) or not isinstance(time_ns, int):
                shared.problem(f"preview_state gave {playing!r}, {time_ns!r}")
            shared.counts["info_calls"] += 1
            shared.beat()
            time.sleep(0.003)
    except BaseException as error:                                                       # noqa: BLE001
        shared.problem(f"the info thread: {type(error).__name__}: {error}")


def watchdog(shared):
    seen, since = -1, time.time()
    while not shared.stop.is_set():
        time.sleep(0.5)
        if shared.progress != seen:
            seen, since = shared.progress, time.time()
        elif time.time() - since > 20 or time.time() - shared.main_beat > 20:
            print("PYTHON STRESS: THE MAIN THREAD, OR EVERYTHING, MOVED NO MORE FOR 20 SECONDS (a deadlock or a stall): the stacks of all threads follow", flush=True)
            faulthandler.dump_traceback(all_threads=True)
            os._exit(3)


def run(seconds=3.0, seed=1, readers=3):
    """Runs the stress for about `seconds`; raises AssertionError with the problems found; returns the counts (and the elapsed time)."""
    base = e.alloc_live()
    shared = Shared()
    rng = random.Random(seed)
    started = time.time()
    switch = sys.getswitchinterval()
    sys.setswitchinterval(0.0005)                                                        # (a thread that waits for the GIL waits half a millisecond, not five)
    with tempfile.TemporaryDirectory() as directory:
        files = [os.path.join(directory, "a.wav"), os.path.join(directory, "b.wav")]
        write_constant_wav(files[0], 8192)                                               # 0.25
        write_constant_wav(files[1], 24576)                                              # 0.75
        graph = Graph()
        nodes = build(graph)                                                             # the sample graph of the editor tests (it has "x", "y" and "free")
        file_node = nodes["file"]
        file_node.set("path", files[0])
        w = graph.add("boundary_inlet", x=10, y=450, name="w")
        r = graph.add("boundary_outlet", x=300, y=450, name="r")
        fr = graph.add("boundary_outlet", x=600, y=450, name="fr")
        graph.connect(w.outlet("out"), r.inlet("in"))
        graph.connect(file_node.outlet("left"), fr.inlet("in"))
        engine = Engine(graph)
        engine.set_audio_backend("null")
        threads = [threading.Thread(target=writer, args=(shared, engine), name="writer"),
                   threading.Thread(target=info, args=(shared, engine, nodes["play"], file_node), name="info"),
                   threading.Thread(target=watchdog, args=(shared,), name="watchdog", daemon=True)]
        threads += [threading.Thread(target=reader, args=(shared, engine, seed * 1000 + i), name=f"reader{i}") for i in range(readers)]
        counters = {"swaps": 0}
        deadline = time.time() + seconds
        try:
            with window(graph, 900, 640) as editor:
                instance = engine.new_instance()
                try:
                    for thread in threads:
                        thread.start()

                    def between(step):
                        installs = 0
                        editor.update()
                        shared.beat()
                        shared.main_beat = time.time()
                        shared.counts["edits"] += 1
                        if step % 17 == 0:                                               # a button of the preview, or its time
                            choice = rng.choice(["play", "play", "pause", "time", "device"])
                            if choice == "time":
                                engine.preview_set_time(nodes["play"].id, rng.randint(-10 ** 9, 10 ** 10))
                            else:
                                engine.action(nodes["play"].id, choice)
                            shared.counts["buttons"] += 1
                        if step % 23 == 0:                                               # the file is replaced and read again
                            counters["swaps"] += 1
                            write_constant_wav(files[counters["swaps"] % 2], 24576 if counters["swaps"] % 2 else 8192)
                            file_node.set("path", files[counters["swaps"] % 2])
                            engine.update()
                            installs += 1
                            engine.action(file_node.id, "open")
                            shared.counts["opens"] += 1
                        if step % 31 == 0:
                            engine.collect()
                            shared.counts["collects"] += 1
                        return installs

                    done = random_edit_run(editor, graph, engine, instance, rng, 10 ** 9, written={nodes["src"].id: 0.0}, protected={w.id, r.id, fr.id},
                                           between=between, stop=lambda: time.time() > deadline or shared.stop.is_set())
                finally:
                    shared.stop.set()
                    for thread in threads:
                        if thread.name != "watchdog":
                            thread.join()
                    instance.close()
        finally:
            shared.stop.set()
            engine.close()
    sys.setswitchinterval(switch)
    shared.counts["edits_by_kind"] = done
    shared.counts["seconds"] = round(time.time() - started, 1)
    assert not shared.problems, "\n".join(shared.problems)
    assert e.alloc_live() == base, f"{e.alloc_live() - base} blocks the engine allocated were not freed"
    return shared.counts
