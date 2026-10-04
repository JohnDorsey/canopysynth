"""The delivery counter: bumped by exactly 1 once per finished prompt that changed code.

src/canopy.h has the same number (CANOPYSYNTH_BUILD) and the DLL exports it; a test checks that they agree. ABI_VERSION is the version of the
node-type descriptor layout (CANOPY_ABI_VERSION in src/canopy_node.h); it changes only when that layout changes."""
CANOPYSYNTH_BUILD = 8
ABI_VERSION = 1
