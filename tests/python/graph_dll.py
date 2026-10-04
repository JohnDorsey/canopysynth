"""Helpers for the graph-model tests: node types written in Python and registered in a real registry (so the descriptors the model reads are
the DLL's own), a catalog of them with the built-in and the hidden test types, and a conversion of a Graph into the C graph description, to
see whether the engine compiles what the model allows. (The real conversion, with the Engine class, is plan step 9.)"""
import engine_dll as e
from canopysynth import NodeTypes
from canopysynth import _descriptor as d
from engine_dll import PyNodeType


def mixer_type():
    """Every setting kind, three inlets with different default knobs, two outlets, an internal rate."""
    return PyNodeType("py.mixer", inlets=[("a", 0.0), ("b", 0.25), ("c", -0.5)], outlets=["out", "aux"],
                      settings=[("count", "int", 7), ("gain", "float", 1.5), ("label", "string", "hi"), ("wav", "path", ""),
                                ("mode", "choice", 1, ["sine", "square", "saw"])],
                      flags=d.FLAG_HAS_INTERNAL_RATE, at=lambda ctx, outlet, t: 0.0)


def versioned_type():
    """A type that is at version 3 (see test_graph.py for what the earlier versions looked like)."""
    made = PyNodeType("py.versioned", inlets=[("level", 0.0), ("pan", 0.0)], outlets=["out", "aux"],
                      settings=[("frequency", "float", 440.0), ("mode", "choice", 0, ["a", "b"])], at=lambda ctx, outlet, t: 0.0)
    made.type.type_version = 3
    return made


def python_types():
    return (mixer_type(), versioned_type())


def make_catalog():
    """The built-in types, the hidden test types and the Python ones, as a NodeTypes catalog (read, then the registry is freed)."""
    rig = e.Rig(*python_types(), test_nodes=True)
    try:
        return NodeTypes.from_registry(rig.registry, e.lib)
    finally:
        rig.close()


def fill(c_graph, graph):
    """Describes `graph` (a canopysynth.Graph) in the C graph `c_graph`: every node, every setting and knob, every connection."""
    for node in graph.nodes():
        assert e.graph_add_node(c_graph, node.id, node.type.encode()) == e.OK
        for desc in node.info.settings:
            value, kind, key = node.settings[desc["key"]], desc["kind"], desc["key"].encode()
            if kind == "int":
                status = e.graph_set_int(c_graph, node.id, key, value)
            elif kind == "choice":
                status = e.graph_set_int(c_graph, node.id, key, desc["choices"].index(value))
            elif kind == "float":
                status = e.graph_set_float(c_graph, node.id, key, value)
            else:
                status = e.graph_set_string(c_graph, node.id, key, value.encode("utf-8"))
            assert status == e.OK
        for inlet in node.info.inlets:
            assert e.graph_set_knob(c_graph, node.id, inlet["key"].encode(), node.knobs[inlet["key"]]) == e.OK
    for connection in graph.connections():
        assert e.graph_connect(c_graph, connection.outlet.node.id, connection.outlet.key.encode(),
                               connection.inlet.node.id, connection.inlet.key.encode()) == e.OK


def compile_in(rig, graph):
    """Fills the rig's C graph from `graph` and compiles it in the rig's engine: (status, the engine's error text)."""
    fill(rig.graph, graph)
    status = e.engine_set_graph(rig.engine, rig.graph)
    return status, (e.engine_last_error(rig.engine) or b"").decode("utf-8")
