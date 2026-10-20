# SPDX-License-Identifier: GPL-3.0-or-later
"""canopysynth: CANOPY, "C Audio Nodes in PYthon". See docs/canopy_design.md for the specification (version 1)."""
from .version import CANOPYSYNTH_BUILD, VERSION as __version__
from .helpers import ns_to_frame, ns_to_frame_fraction
from .errors import BoundaryError, GraphError, QueryError
from .catalog import NodeTypes, register_migration
from .graph import BoundaryInfo, Connection, Graph, Node, Port
from .engine import Engine, Instance


def __getattr__(name):
    """`canopysynth.Editor` (needs tkinter) is imported when it is first asked for, so that a program that only builds, saves and runs graphs does not
    load tkinter."""
    if name == "Editor":
        from .editor import Editor
        return Editor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
