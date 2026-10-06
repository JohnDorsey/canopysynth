"""The delivery counter: bumped by exactly 1 once per finished prompt that changed code.

src/canopy.h has the same number (CANOPYSYNTH_BUILD) and the DLL exports it; a test checks that they agree. ABI_VERSION is the version of the
node-type descriptor layout and handler contracts (CANOPY_ABI_VERSION in src/canopy_node.h); it changes only when those change (2: a point query
returns a status and writes its answer)."""
CANOPYSYNTH_BUILD = 17
ABI_VERSION = 2
