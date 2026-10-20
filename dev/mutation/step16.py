# SPDX-License-Identifier: GPL-3.0-or-later
"""The mutations for the licence change (build 21): the licence text, the line in the source files, the wheel's metadata and files, the folder, the README, and the old name of
the host program. All of them are Python or text files, so the runner skips the build and the C tests, and AREAS limits the tests to test_license.py and test_package.py (which
makes the packages, so each run of it takes about 25 s). Run with
    python dev/mutation/mutate.py dev/mutation/step16.py
Every one should be reported as caught."""
K = "dev/package.py"
L = "LICENSE"
R = "README.md"

AREAS = ["license", "package"]

MUTATIONS = [
    ("L01 the package script names another licence", K, 'LICENSE_ID = "GPL-3.0-or-later"', 'LICENSE_ID = "GPL-2.0-or-later"'),
    ("L02 the wheel does not carry the LICENSE file", K, '    entries[f"{info}/licenses/LICENSE"] = to_bytes(text_file(os.path.join(ROOT, "LICENSE")))\n', ""),
    ("L03 the wheel's metadata does not name the licence", K, '        f"License: {LICENSE_ID}",\n', ""),
    ("L04 the wheel's classifier says version 2", K, "GNU General Public License v3 or later (GPLv3+)", "GNU General Public License v2 or later (GPLv2+)"),
    ("L05 the unzip-and-run folder has no LICENSE", K, '        "LICENSE": os.path.join(ROOT, "LICENSE"),\n', ""),
    ("L06 the LICENSE file is the text of version 2", L, "Version 3, 29 June 2007", "Version 2, June 1991"),
    ("L07 the README names another licence", R, "(SPDX: `GPL-3.0-or-later`)", "(SPDX: `MIT`)"),
    ("L08 the README says again that no licence has been chosen", R, "## Licence\n", "## Licence\n\nNo licence has been chosen for CANOPY itself yet.\n"),
    ("L09 a Python file of the package has no licence line", "canopysynth/errors.py", "# SPDX-License-Identifier: GPL-3.0-or-later\n", ""),
    ("L10 a Python file of the tests names another licence", "tests/python/engine_dll.py", "SPDX-License-Identifier: GPL-3.0-or-later", "SPDX-License-Identifier: GPL-3.0-only"),
    ("L11 the PowerShell build script has no licence line", "build.ps1", "# SPDX-License-Identifier: GPL-3.0-or-later\n", ""),
    ("L12 the batch file would print its licence line", "run_editor.bat", "@rem SPDX-License-Identifier: GPL-3.0-or-later", "rem SPDX-License-Identifier: GPL-3.0-or-later"),
    ("L13 the design names the host program by its old name", "docs/canopy_design.md", "it does not depend on PrismaticFractals", "it does not depend on light" + "_bounces"),
]
