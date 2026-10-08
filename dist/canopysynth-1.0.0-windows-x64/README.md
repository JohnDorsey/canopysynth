# CANOPY (`canopysynth`)

CANOPY ("C Audio Nodes in PYthon") is a small node-graph engine for audio and for audio-driven numbers, meant to be embedded in Python programs that
have a tkinter window, for example programs that generate video. You connect nodes together in an editor panel; a C engine answers questions of the form
"what is this outlet's value at time t" or "give me n samples of it between t0 and t1", fast enough for realtime playback; and your program reads
the answers through a short Python API.

Version 1, Windows 64-bit, Python 3.9 or newer with tkinter (tested on 3.11). No other Python packages are needed.

## Start the editor

**From the unzipped folder** (no installation): double-click `run_editor.bat`. To open a saved graph, drag its `.json` file onto the batch file.

**With pip:**

```
pip install canopysynth-1.0.0-py3-none-win_amd64.whl
canopysynth-editor                  (or: python -m canopysynth)
```

**Without pip, from Python:** put the folder that contains `canopysynth/` on `sys.path` and import it:

```python
import sys
sys.path.insert(0, r"C:\tools\canopysynth-1.0.0-windows-x64")
import canopysynth
```

## Use it from a program

```python
import canopysynth

graph = canopysynth.Graph()
x = graph.add("boundary_inlet", name="x")            # the host writes here
y = graph.add("boundary_outlet", name="y")           # the host reads here
graph.connect(x.outlet("out"), y.inlet("in"))

with canopysynth.Engine(graph) as engine:
    engine.set_boundary("x", 0.7)
    with engine.new_instance() as instance:
        print(instance.value("y", 0))                # 0.7
```

`examples/section15.py` is the whole example of the design document (a WAV file, the editor, the engine, queries). Next:

- **`docs/user_guide.md`** — the editor, the built-in nodes, the Python API, time, threads, errors.
- **`docs/node_author_guide.md`** — writing a node type in C (the registration API), with a worked example in `examples/`.
- **`docs/canopy_design.md`** — the specification everything is built to.

## What is in the folder

| | |
|---|---|
| `run_editor.bat` | starts the editor |
| `canopysynth/` | the Python package, with `canopysynth.dll` (the engine), `include/` (the C headers) and `lib/` (the import library) |
| `docs/` | the guides, the design, third-party notices |
| `examples/` | the section 15 program, a node written in C and the Python that uses it |

`canopysynth.dll` needs no Visual C++ redistributable (it links the C runtime statically and imports only `KERNEL32.dll`).

## Building from source

Needs Visual Studio 2022 with the C++ tools (the "C++ AddressSanitizer" component is optional) and Python.

```
python run_tests.py                    build and run every test
python dev/package.py                  write dist/canopysynth-1.0.0-py3-none-win_amd64.whl and dist/canopysynth-1.0.0-windows-x64.zip
```

`CLAUDE.md` lists every command; `docs/canopy_plan.md` is the build plan and its log. No licence has been chosen for CANOPY itself yet. The two third-party
libraries inside the DLL (dr_wav and miniaudio) are public domain / MIT-0 (`docs/THIRD_PARTY_NOTICES.txt`).
