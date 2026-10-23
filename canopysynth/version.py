# SPDX-License-Identifier: GPL-3.0-or-later
"""The delivery counter: bumped by exactly 1 once per finished prompt that changed code.

src/canopy.h has the same number (CANOPYSYNTH_BUILD) and the DLL exports it; a test checks that they agree. ABI_VERSION is the version of the
node-type descriptor layout and handler contracts (CANOPY_ABI_VERSION in src/canopy_node.h); it changes only when those change (2: a point query
returns a status and writes its answer)."""
CANOPYSYNTH_BUILD = 24
VERSION = "1.0.0"            # the release version of the packages dev/package.py makes (the wheel and the folder); the delivery counter above is not part of it
ABI_VERSION = 2
