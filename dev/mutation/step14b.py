"""The mutations for plan step 14's other files: run_editor.bat, the example node and the documents, as a FOCUSED campaign (see mutate.py: ARGS and ENV): only the tests of
the packages and of the documents judge each fault (and the C tests are cut down to one cheap one, since the build still runs after a change to a C file). Run with
    python dev/mutation/mutate.py dev/mutation/step14b.py
Every one of them should be reported as caught. Not here: the default knob of the example's `gain` inlet (its use script sets the knob itself, so the value cannot
be seen) and the Python version check of the batch file (the tests run on a newer Python)."""
BAT = "run_editor.bat"
C = "examples/example_node.c"
G = "docs/user_guide.md"
N = "docs/node_author_guide.md"

ENV = {"CANOPY_C_TESTS": "the_build_number_function_returns_the_header_constant"}
ARGS = ["package", "docs"]

MUTATIONS = [
    ("B01 the batch file reports success when the editor failed", BAT, ":console\n%RUN% -m canopysynth %*\nexit /b %errorlevel%", ":console\n%RUN% -m canopysynth %*\nexit /b 0"),
    ("B02 the batch file does not put its folder on the path", BAT, 'set "PYTHONPATH=%~dp0;%PYTHONPATH%"\n', ""),
    ("B03 the batch file drops the arguments it is given", BAT, ":console\n%RUN% -m canopysynth %*", ":console\n%RUN% -m canopysynth"),
    ("B04 the batch file does not know the console switch", BAT, 'if "%CANOPY_CONSOLE%"=="1" goto console', 'if "%CANOPY_SHOW%"=="1" goto console'),
    ("E01 the example node adds the gain instead of multiplying", C, "out[i] = (float)((double)out[i] * (double)gain[i] + offset);", "out[i] = (float)((double)out[i] + (double)gain[i] + offset);"),
    ("E02 the example node has another key", C, 'type.key = "example.scale";', 'type.key = "example.scaler";'),
    ("E03 the example node's point query forgets the offset", C, "*out = (float)((double)in * (double)gain + canopy_ctx_float(ctx, SETTING_OFFSET));", "*out = (float)((double)in * (double)gain);"),
    ("E04 the example node declares no scratch buffer", C, "type.scratch_buffers = 1; ", "type.scratch_buffers = 0; "),
    ("D01 the guide's helper-function example does not print the fraction", G, "print(n, frame, round(fraction, 3))", "print(n, frame)"),
    ("D02 the guide writes a boundary that the graph does not have", G, '    engine.set_boundary("x", 0.7)                # any thread, any float (nothing is clamped)', '    engine.set_boundary("z", 0.7)                # any thread, any float (nothing is clamped)'),
    ("D03 the compile command of the guide leaves out the header folder", N, "/LD examples\\example_node.c /I canopysynth\\include /Fe:", "/LD examples\\example_node.c /Fe:"),
    ("D04 the README does not point at the user guide", "README.md", "- **`docs/user_guide.md`** —", "- **the user guide** —"),
]
