"""The exceptions of the package (design section 15)."""


class GraphError(Exception):
    """A graph cannot be built, compiled or loaded: an unknown node type, a bad setting, knob or connection, a file that is not in the format. The
    message says which node, key or name is at fault. (Faults about boundary nodes and their names are BoundaryError.)"""


class BoundaryError(Exception):
    """A problem with a boundary node or its name (design sections 10 and 16): the graph has no boundary node of the name that was asked for (or it is
    one of the other kind), a name that cannot be one, or a boundary node whose name is empty or used twice, which the graph editing allows and
    compiling refuses. The message names the boundary node or the name."""


class QueryError(Exception):
    """A query returned a nonzero status (design sections 5 and 15). `status` is the code of src/canopy.h (CANOPY_ERR_N = 3, CANOPY_ERR_OVERFLOW = 2,
    CANOPY_ERR_BUSY = 14...); the message is the DLL's sentence for it, with what was asked."""

    def __init__(self, status, text):
        super().__init__(text)
        self.status = status
