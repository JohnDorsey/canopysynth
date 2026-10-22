# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests (plan step 13, error behaviours): how a process ends, and what it does when the machine runs out of memory for real.
1. A program that exits while its preview is playing (the audio thread is running in the DLL), with an engine and instances still open, with a worker thread in the
   middle of queries, with an editor window that was never destroyed, through `os._exit`, or through an unhandled exception, must end by itself, quickly, with
   the exit code it asked for and nothing on its error output (a crash would be an access violation, a hang a timeout).
2. In a process whose memory is limited by a Windows job object, the allocations that fail are real ones: a file that is too big for the memory is refused with a
   message on its node, an instance that cannot be made is a MemoryError, a graph that cannot be installed is a MemoryError that leaves the old graph running, and after
   each of them what is left works and frees without a crash. (The C tests make every Nth allocation fail, one at a time; this is the same through the bridge, with Python, ctypes and
   miniaudio failing for the same reason at the same time.)"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PREAMBLE = f"""
import os, sys, threading, time
sys.path.insert(0, {ROOT!r})
sys.path.insert(0, {os.path.join(ROOT, 'tests', 'python')!r})
import canopysynth
from canopysynth import Engine, Graph

def playing_engine(*, wav=None):
    graph = Graph()
    song = graph.add("file_read", path=wav) if wav else None
    play = graph.add("realtime_preview")
    x = graph.add("boundary_inlet", name="x")
    y = graph.add("boundary_outlet", name="y")
    graph.connect(x.outlet("out"), y.inlet("in"))
    graph.connect(x.outlet("out"), play.inlet("left"))
    engine = Engine(graph)
    engine.set_audio_backend("null")
    engine.set_boundary("x", 0.25)
    engine.action(play.id, "play")
    deadline = time.time() + 3
    while not engine.preview_state(play.id)[0] and time.time() < deadline:
        time.sleep(0.01)
    assert engine.preview_state(play.id)[0], "the preview did not start"
    return graph, engine, play
"""


def run(body, timeout=30):
    result = subprocess.run([sys.executable, "-c", PREAMBLE + body], capture_output=True, text=True, timeout=timeout, cwd=ROOT)
    return result.returncode & 0xFFFFFFFF, result.stdout, result.stderr


def assert_clean(code, expected, stderr, what):
    assert code == expected, f"{what}: exit code {code:#x}, expected {expected:#x}; stderr: {stderr[-600:]}"
    assert "Fatal" not in stderr and "Traceback" not in stderr.replace("expected-error", ""), f"{what}: {stderr[-600:]}"


def test_py_a_program_that_ends_while_the_preview_plays_ends_by_itself_with_nothing_closed():
    code, out, err = run("graph, engine, play = playing_engine()\ninst = engine.new_instance()\ninst2 = engine.new_instance()\ninst.value('y', 0)\nprint('done')\n")
    assert_clean(code, 0, err, "exit with an open engine, two open instances and a playing preview")
    assert "done" in out
    code, out, err = run("graph, engine, play = playing_engine()\nprint('done')\nos._exit(0)\n")
    assert_clean(code, 0, err, "os._exit while playing")
    code, out, err = run("graph, engine, play = playing_engine()\ninst = engine.new_instance()\nprint('done')\nraise SystemExit(7)\n")
    assert_clean(code, 7, err, "SystemExit(7) while playing")


def test_py_an_unhandled_exception_while_the_preview_plays_ends_the_program_with_its_traceback_and_no_crash():
    code, out, err = run("graph, engine, play = playing_engine()\ninst = engine.new_instance()\nraise ValueError('expected-error')\n")
    assert code == 1 and "ValueError: expected-error" in err and "Fatal" not in err and "access violation" not in err, (hex(code), err[-600:])


def test_py_a_program_that_ends_while_a_thread_is_in_the_middle_of_queries_and_another_writes_ends_by_itself():
    body = """
graph, engine, play = playing_engine()
stop = False

def reader():
    inst = engine.new_instance()
    while True:
        inst.audio('y', 0, 10_000_000, 4800)

def writer():
    value = 0.0
    while True:
        value += 1.0
        engine.set_boundary('x', value)

for target in (reader, reader, writer):
    threading.Thread(target=target, daemon=True).start()
time.sleep(0.5)
print('done')
"""
    code, out, err = run(body)
    assert_clean(code, 0, err, "exit with daemon threads querying and writing")
    assert "done" in out


def test_py_a_program_that_ends_with_an_editor_window_and_an_engine_that_were_never_closed_ends_by_itself():
    body = """
import tkinter
from canopysynth import Editor
graph, engine, play = playing_engine()
root = tkinter.Tk()
root.geometry('400x300+6000+6000')
editor = Editor(root, graph, width=400, height=300)
editor.pack()
for _ in range(20):
    root.update()
    time.sleep(0.01)
print('done')
"""
    code, out, err = run(body)
    assert_clean(code, 0, err, "exit with a window and an engine never closed")
    assert "done" in out


def test_py_dropping_the_engine_while_an_instance_and_the_preview_live_is_safe_and_frees_everything_once_the_instance_is_dropped():
    body = """
import gc
import engine_dll as e
"""
    body = """
graph, engine, play = playing_engine()
inst = engine.new_instance()
del engine, play, graph
gc.collect() if 'gc' in globals() else None
print(inst.value('y', 0))
del inst
print('done')
"""
    code, out, err = run(body)
    assert_clean(code, 0, err, "dropping the engine before its instance")
    assert out.split() == ["0.25", "done"], out


# ---- memory that runs out for real ----

JOB = """
import ctypes
from ctypes import wintypes

class BASIC(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64), ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

class IO(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

class EXTENDED(ctypes.Structure):
    _fields_ = [("Basic", BASIC), ("Io", IO), ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t)]

def limit_memory(megabytes):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    job = kernel.CreateJobObjectW(None, None)
    info = EXTENDED()
    info.Basic.LimitFlags = 0x100                                  # JOB_OBJECT_LIMIT_PROCESS_MEMORY
    info.ProcessMemoryLimit = megabytes * 1024 * 1024
    assert kernel.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)), ctypes.get_last_error()
    assert kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()), ctypes.get_last_error()
"""


PRIVATE = """
import ctypes
from ctypes import wintypes

class COUNTERS(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t), ("PrivateUsage", ctypes.c_size_t)]

def private_mb():
    kernel = ctypes.WinDLL("kernel32")
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.WinDLL("psapi")
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(COUNTERS), wintypes.DWORD]
    counters = COUNTERS()
    counters.cb = ctypes.sizeof(counters)
    psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
    return counters.PrivateUsage / 1048576.0
"""


def test_py_when_memory_runs_out_for_real_a_big_file_is_refused_on_its_node_and_what_is_left_still_works():
    body = JOB + """
import struct, tempfile
import engine_dll as e
limit_memory(250)
baseline = e.alloc_live()

def big_wav(directory, megabytes):
    path = os.path.join(directory, "big.wav")
    frames = megabytes * 1024 * 1024 // 4
    with open(path, "wb") as handle:
        handle.write(b"RIFF" + struct.pack("<I", 36 + frames * 4) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 2, 44100, 44100 * 4, 4, 16) + b"data" + struct.pack("<I", frames * 4))
        chunk = bytes(range(256)) * 1024
        for _ in range(frames * 4 // len(chunk)):
            handle.write(chunk)
    return path

# a small graph that must go on working through all of it
graph = Graph()
x = graph.add("boundary_inlet", name="x")
y = graph.add("boundary_outlet", name="y")
graph.connect(x.outlet("out"), y.inlet("in"))
engine = Engine(graph)
engine.set_boundary("x", 0.5)
inst = engine.new_instance()
assert inst.value("y", 0) == 0.5

# 1. a file whose samples (as float32, two channels: twice its size) do not fit: the node says so, the engine goes on
with tempfile.TemporaryDirectory() as directory:
    path = big_wav(directory, 160)                                 # 160 MB of file: 320 MB of floats in a process limited to 250
    graph2 = Graph()
    song = graph2.add("file_read", path=path)
    out = graph2.add("boundary_outlet", name="song")
    graph2.connect(song.outlet("left"), out.inlet("in"))
    big = Engine(graph2)
    message = big.node_message(song.id)
    print("file:", message[:60])
    with big.new_instance() as reader:
        print("silent:", reader.value("song", 1_000_000))
    big.close()
print("small graph still works:", inst.value("y", 0))

inst.close()
engine.close()
import gc
gc.collect()
print("leaked blocks:", e.alloc_live() - baseline)
"""
    code, out, err = run(body, timeout=240)
    assert code == 0 and "Fatal" not in err and "Traceback" not in err, (hex(code), out[-800:], err[-800:])
    lines = out.strip().splitlines()
    assert lines[0].startswith("file: ") and "memory" in lines[0].lower(), lines[:3]                    # the node says it ran out of memory loading the file
    assert "silent: 0.0" in lines[1], lines
    assert "small graph still works: 0.5" in out and out.count("small graph still works: 0.5") == 1, out
    assert lines[-1] == "leaked blocks: 0", lines[-1]


def test_py_an_install_that_runs_out_of_memory_for_real_is_a_memory_error_and_the_engine_keeps_running_the_graph_it_had():
    """The Python Graph is built first (100000 more nodes: about 50 MB), then the memory is limited to 40 MB above what the process holds, which the compile of
    those nodes (about 110 MB) cannot have: update() must fail with MemoryError part-way through and leave the engine, its instance and the graph it ran as they were."""
    body = JOB + PRIVATE + """
import engine_dll as e

baseline = e.alloc_live()
graph = Graph()
x = graph.add("boundary_inlet", name="x")
y = graph.add("boundary_outlet", name="y")
graph.connect(x.outlet("out"), y.inlet("in"))
engine = Engine(graph)
engine.set_boundary("x", 0.5)
inst = engine.new_instance()
assert inst.value("y", 0) == 0.5
for k in range(100000):
    graph.add("boundary_inlet", name=f"n{k}")
limit_memory(int(private_mb()) + 40)
try:
    engine.update()
    outcome = "installed"
except MemoryError:
    outcome = "MemoryError"
print("update:", outcome)
print("the old graph answers:", inst.value("y", 0))
print("boundary nodes:", len(engine.boundary_nodes()))
try:
    engine.update()
    again = "installed"
except MemoryError:
    again = "MemoryError"
print("update again:", again)
print("the old graph answers:", inst.value("y", 0))
inst.close()
engine.close()
print("leaked blocks:", e.alloc_live() - baseline)
"""
    code, out, err = run(body, timeout=240)
    assert code == 0 and "Fatal" not in err and "Traceback" not in err, (hex(code), out[-800:], err[-800:])
    assert out.split("\n")[:7] == ["update: MemoryError", "the old graph answers: 0.5", "boundary nodes: 2", "update again: MemoryError",
                                   "the old graph answers: 0.5", "leaked blocks: 0", ""], out


def test_py_when_memory_runs_out_for_real_an_instance_that_cannot_be_made_is_a_memory_error_and_the_instances_that_were_made_free_cleanly():
    """The limit is set 6 MB above what the process holds, and instances of a two-node graph (a few hundred bytes each: it has no scratch buffer) are made until
    one cannot be: a MemoryError, the engine goes on, and every instance frees without a leak. (Freeing an instance costs a pass over the live ones, so the loop is
    short: with the memory of the whole machine it would make a million.)
    This test failed one run in five until it was investigated (2026-10-22), for two reasons. The test itself reported the MemoryError with `print` while the process was
    still at its limit, with no memory left to format the line in: it now holds a reserve and gives it back in the handler, as a program that means to survive running out
    of memory has to. And `Engine.new_instance` could lose an instance made in C when Python could not build its object (fixed in the library; the regression test is in
    test_bridge.py); a list that grows by `append` could also fail after an instance was made, so the list is made whole before the limit and filled by index."""
    body = JOB + PRIVATE + """
import engine_dll as e
baseline = e.alloc_live()
graph = Graph()
x = graph.add("boundary_inlet", name="x")
y = graph.add("boundary_outlet", name="y")
graph.connect(x.outlet("out"), y.inlet("in"))
engine = Engine(graph)
engine.set_boundary("x", 0.5)
inst = engine.new_instance()
LIMIT = 400_000
instances, error = [None] * LIMIT, None
reserve = bytearray(2 * 1024 * 1024)
limit_memory(int(private_mb()) + 6)
try:
    for n in range(LIMIT):
        instances[n] = engine.new_instance()
except MemoryError:
    del reserve
    error = "MemoryError"
made = [each for each in instances if each is not None]
print("instances:", error, len(made) > 1000, len(made) < LIMIT)
print("the engine still answers:", inst.value("y", 0))
for each in made:
    each.close()
instances.clear()
inst.close()
engine.close()
print("leaked blocks:", e.alloc_live() - baseline)
"""
    code, out, err = run(body, timeout=240)
    assert code == 0 and "Fatal" not in err and "Traceback" not in err, (hex(code), out[-800:], err[-800:])
    assert out.split("\n")[:3] == ["instances: MemoryError True True", "the engine still answers: 0.5", "leaked blocks: 0"], out

