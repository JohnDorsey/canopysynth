# SPDX-License-Identifier: GPL-3.0-or-later
"""Uses the node type of examples/example_node.c from Python (docs/node_author_guide.md): loads its DLL, registers the type in a registry, and builds a
graph and an engine over that registry.

    python examples/use_example_node.py [path to example_node.dll]

Prints the result of a few queries and exits 0 when they are what the node's formula says. A registry that holds a host's own node types is the one
place a Python program touches the DLL's C interface itself (the other calls are wrapped by Graph and Engine); `canopysynth._lib.DLL_PATH` is the one
private name used here."""
import ctypes
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.isdir(os.path.join(os.path.dirname(HERE), "canopysynth")):           # run from an unzipped folder, not installed: find the package next to examples/
    sys.path.insert(0, os.path.dirname(HERE))

import canopysynth                                                  # noqa: E402
from canopysynth import _lib                                        # noqa: E402


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "example_node.dll")
    lib = ctypes.CDLL(_lib.DLL_PATH)                            # (the same file Graph and Engine load: Windows gives back the loaded one)
    lib.canopy_registry_new.restype = ctypes.c_void_p
    lib.canopy_registry_free.argtypes = [ctypes.c_void_p]
    example = ctypes.CDLL(os.path.abspath(path))
    example.canopy_example_register.argtypes = [ctypes.c_void_p]
    example.canopy_example_register.restype = ctypes.c_int32

    registry = lib.canopy_registry_new()                        # the built-in node types, and ours is added to it
    status = example.canopy_example_register(registry)
    if status != 0:
        raise SystemExit(f"the node type was refused: status {status}")
    types = canopysynth.NodeTypes.from_registry(registry, lib)  # what a Graph may name
    try:
        graph = canopysynth.Graph(types=types)
        source = graph.add("boundary_inlet", name="x")
        scale = graph.add("example.scale", offset=0.25)         # its setting, by key
        out = graph.add("boundary_outlet", name="y")
        graph.connect(source.outlet("out"), scale.inlet("in"))
        graph.connect(scale.outlet("out"), out.inlet("in"))
        scale.set_knob("gain", -0.5)

        with canopysynth.Engine(graph, registry=registry) as engine:     # the engine borrows the registry: it must outlive the engine
            engine.set_boundary("x", 0.8)
            with engine.new_instance() as instance:
                point = instance.value("y", 0)
                span = instance.audio("y", 0, 1_000_000, 4)
            print("point:", point, "span:", list(span))
            expected = 0.8 * -0.5 + 0.25                        # in * gain + offset
            assert abs(point - expected) < 1e-6 and all(abs(v - expected) < 1e-6 for v in span), (point, list(span), expected)
    finally:
        lib.canopy_registry_free(registry)
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
