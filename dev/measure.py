"""The timing measurements of plan step 13: what the Python bridge and the editor cost, and a runner for the C measurements of build\\bench.exe
(`powershell -File build.ps1 -Bench` builds it). The numbers are for the machine and the build they were taken on; they say how a cost grows with the size of
the graph and what a host can expect of a call.
    python dev/measure.py bridge      what a call through the public API costs (point and span queries, boundary and knob writes), how queries scale over
                                      threads (the C calls let go of the GIL), and what building, compiling and saving a graph costs for 10 to 3000 nodes
    python dev/measure.py editor      what the editor costs (a redraw, an edit that recompiles, the timer's poll) for 10 to 500 nodes, in an off-screen window
    python dev/measure.py c           runs bench.exe: queries, scaling, installs, stalls, preview, files of 1, 10 and 100 MB, deep chains
    python dev/measure.py device      the preview on the machine's real audio device, playing silence (bench.exe device --real-device)
    python dev/measure.py             bridge, editor and c"""
import os
import statistics
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests", "python"))
BENCH = os.path.join(ROOT, "build", "bench.exe")


def timed(function, repeats):
    """Microseconds per call of `function`, the best of three rounds of `repeats` calls."""
    best = None
    for _ in range(3):
        start = time.perf_counter_ns()
        for _ in range(repeats):
            function()
        took = (time.perf_counter_ns() - start) / repeats / 1000.0
        best = took if best is None or took < best else best
    return best


def measure_bridge():
    import canopysynth
    from canopysynth import Engine, Graph
    print("BRIDGE (Python %s; one thread unless said otherwise; the best of three rounds)" % sys.version.split()[0])
    graph = Graph()
    source = graph.add("boundary_inlet", name="x")
    sink = graph.add("boundary_outlet", name="y")
    graph.connect(source.outlet("out"), sink.inlet("in"))
    with Engine(graph) as engine, engine.new_instance() as instance:
        engine.set_boundary("x", 0.5)
        print(f"  Instance.value (a point query of a boundary outlet)         {timed(lambda: instance.value('y', 0), 20000):8.2f} us/call")
        for n in (1, 64, 480, 4800, 65536):
            repeats = max(20, 200000 // max(n, 64))
            took = timed(lambda: instance.audio("y", 0, 10_000_000, n), repeats)
            print(f"  Instance.audio, a span of {n:5d} samples                       {took:8.2f} us/call = {took * 1000.0 / n:8.2f} ns/sample (the memoryview included)")
        print(f"  Engine.set_boundary                                         {timed(lambda: engine.set_boundary('x', 0.25), 20000):8.2f} us/call")
        print(f"  Engine.boundary_nodes (2 nodes)                             {timed(engine.boundary_nodes, 3000):8.2f} us/call")
        print(f"  Engine.collect                                              {timed(engine.collect, 3000):8.2f} us/call")
        print(f"  Engine.update (4 nodes, nothing changed)                    {timed(engine.update, 300):8.2f} us/call")
        print(f"  canopysynth.ns_to_frame (the Python helper)                 {timed(lambda: canopysynth.ns_to_frame(123456789, 48000), 50000):8.2f} us/call")
        for threads in (1, 2, 4, 8):
            counts, stop = [0] * threads, threading.Event()

            def worker(slot):
                with engine.new_instance() as mine:
                    while not stop.is_set():
                        mine.audio("y", 0, 100_000_000, 4800)
                        counts[slot] += 1

            workers = [threading.Thread(target=worker, args=(slot,)) for slot in range(threads)]
            start = time.perf_counter()
            for worker_thread in workers:
                worker_thread.start()
            time.sleep(1.0)
            stop.set()
            for worker_thread in workers:
                worker_thread.join()
            rate = sum(counts) / (time.perf_counter() - start)
            if threads == 1:
                single = rate
            print(f"  {threads} thread(s) asking spans of 4800 samples: {rate:10.0f} spans/s = {rate / single:4.2f}x one thread")
    print("  spans that cost the engine something (65536 samples of a 4 MB WAV file, about 0.3 ms of C each: the GIL is let go during it):")
    with tempfile.TemporaryDirectory() as directory:
        from test_fileread import write_wav
        path = os.path.join(directory, "bench.wav")
        write_wav(path, 1, 16, 2, 44100, bytes(range(256)) * 16384)
        song_graph = Graph()
        song = song_graph.add("file_read", path=path)
        out = song_graph.add("boundary_outlet", name="y")
        song_graph.connect(song.outlet("left"), out.inlet("in"))
        with Engine(song_graph) as song_engine:
            for threads in (1, 2, 4, 8):
                counts, stop = [0] * threads, threading.Event()

                def song_worker(slot):
                    with song_engine.new_instance() as mine:
                        while not stop.is_set():
                            mine.audio("y", 0, 1_000_000_000, 65536)
                            counts[slot] += 1

                workers = [threading.Thread(target=song_worker, args=(slot,)) for slot in range(threads)]
                start = time.perf_counter()
                for worker_thread in workers:
                    worker_thread.start()
                time.sleep(1.5)
                stop.set()
                for worker_thread in workers:
                    worker_thread.join()
                rate = sum(counts) / (time.perf_counter() - start)
                if threads == 1:
                    single = rate
                print(f"  {threads} thread(s) asking spans of 65536 samples of a file: {rate:8.0f} spans/s = {rate / single:4.2f}x one thread")
    print("  building, compiling and saving a graph of N boundary nodes (N/2 inlets, each wired to an outlet):")
    for count in (10, 100, 1000, 3000):
        graph = Graph()
        start = time.perf_counter()
        for k in range(count // 2):
            inlet = graph.add("boundary_inlet", name=f"i{k}")
            outlet = graph.add("boundary_outlet", name=f"o{k}")
            graph.connect(inlet.outlet("out"), outlet.inlet("in"))
        built = time.perf_counter() - start
        unprotected = Graph()
        unprotected.loop_protection = False                                              # (every connect then skips the search for a loop)
        start = time.perf_counter()
        for k in range(count // 2):
            inlet = unprotected.add("boundary_inlet", name=f"i{k}")
            outlet = unprotected.add("boundary_outlet", name=f"o{k}")
            unprotected.connect(inlet.outlet("out"), outlet.inlet("in"))
        unprotected.loop_protection = True                                               # (and one search at the end)
        built_unprotected = time.perf_counter() - start
        start = time.perf_counter()
        engine = Engine(graph)
        first = time.perf_counter() - start
        start = time.perf_counter()
        engine.update()
        again = time.perf_counter() - start
        start = time.perf_counter()
        engine.boundary_nodes()
        listed = time.perf_counter() - start
        start = time.perf_counter()
        saved = graph.to_dict()
        to_dict = time.perf_counter() - start
        start = time.perf_counter()
        Graph.from_dict(saved)
        from_dict = time.perf_counter() - start
        engine.close()
        print(f"    {count:5d} nodes: build the Graph {built * 1000:8.2f} ms (with loop protection off while building: {built_unprotected * 1000:7.2f} ms), Engine(graph) {first * 1000:8.2f} ms, update() again {again * 1000:8.2f} ms, boundary_nodes "
              f"{listed * 1000:7.2f} ms, to_dict {to_dict * 1000:7.2f} ms, from_dict {from_dict * 1000:8.2f} ms")


def measure_editor():
    import tkinter
    from canopysynth import Engine, Graph
    from test_editor import window
    print("EDITOR (an off-screen 900 x 640 window; one engine linked, null audio; the best of several rounds)")
    for count in (10, 50, 200, 500):
        graph = Graph()
        for k in range(count // 2):
            inlet = graph.add("boundary_inlet", x=(k % 20) * 120, y=(k // 20) * 90, name=f"i{k}")
            outlet = graph.add("boundary_outlet", x=(k % 20) * 120 + 60, y=(k // 20) * 90 + 40, name=f"o{k}")
            graph.connect(inlet.outlet("out"), outlet.inlet("in"))
        engine = Engine(graph)
        engine.set_audio_backend("null")
        try:
            with window(graph, 900, 640) as editor:
                redraws, adds, polls = [], [], []
                for _ in range(5):
                    start = time.perf_counter()
                    editor.redraw()
                    editor.update()
                    redraws.append(time.perf_counter() - start)
                link = editor._engine_links()[0]
                for _ in range(20):
                    start = time.perf_counter()
                    link.poll()
                    polls.append(time.perf_counter() - start)
                for k in range(5):
                    start = time.perf_counter()
                    node = editor.add_node("boundary_outlet", 10 + 5 * k, 600)
                    editor.update()
                    adds.append(time.perf_counter() - start)
                    editor.edit_setting(node, "name", f"extra{k}")
                print(f"  {count:4d} nodes: a full redraw {min(redraws) * 1000:8.2f} ms, an edit that recompiles (add a node, with the redraw) {min(adds) * 1000:8.2f} ms, "
                      f"the timer's poll (every 100 ms) {min(polls) * 1000:7.3f} ms")
        finally:
            engine.close()


def run_bench(arguments, timeout=300):
    if not os.path.exists(BENCH):
        raise SystemExit("build\\bench.exe is not built: powershell -ExecutionPolicy Bypass -File build.ps1 -Bench")
    started = time.time()
    result = subprocess.run([BENCH] + arguments, capture_output=True, text=True, timeout=timeout)
    sys.stdout.write(result.stdout)
    if result.returncode != 0:
        print(f"  (exit code {result.returncode:#x})")
    return result, time.time() - started


def measure_c():
    for arguments in (["queries"], ["scaling"], ["installs"], ["stalls"], ["preview"], ["file", "1"], ["file", "10"], ["file", "100"]):
        run_bench(arguments, timeout=600)
        print()
    print("DEEP CHAINS (a chain of N gains, each asked once as a point and as spans of 64 and 65536; one process for each try; 0xc00000fd is a stack overflow)")
    for mode in ("main", "worker", "preview"):
        last_ok = 0
        for depth in (100, 500, 1000, 1500, 2000, 2500, 3000, 3500, 4000, 8000, 16000, 32000, 64000, 128000):
            try:
                result = subprocess.run([BENCH, "chain", str(depth), mode], capture_output=True, text=True, timeout=120)
                outcome = "ok" if result.returncode == 0 else f"ended with exit code {result.returncode & 0xffffffff:#x}"
                where = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "(no output)"
            except subprocess.TimeoutExpired:
                outcome, where = "did not finish within 120 s", ""
            print(f"  {mode:8s} depth {depth:7d}: {outcome:38s} {where[:90]}")
            if outcome == "ok":
                last_ok = depth
            else:
                break
        print(f"  {mode:8s} the deepest chain that was answered of those tried: {last_ok}")


def measure_device():
    print("(this opens the machine's real default audio device and plays silence)")
    run_bench(["device", "--real-device"], timeout=120)


def main(argv):
    parts = argv or ["bridge", "editor", "c"]
    print(f"machine: {os.cpu_count()} logical processors, {sys.platform}, Python {sys.version.split()[0]}\n")
    for part in parts:
        {"bridge": measure_bridge, "editor": measure_editor, "c": measure_c, "device": measure_device}[part]()
        print()


if __name__ == "__main__":
    main(sys.argv[1:])
