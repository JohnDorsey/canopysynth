"""The mutations for plan step 14's Python code: the packaging script (dev/package.py) and the stand-alone editor (canopysynth/app.py). Run with
    python dev/mutation/mutate.py dev/mutation/step14.py
They are all Python files, so the runner skips the build and the C tests, and AREAS limits the tests to the files written for them (test_package.py makes the packages
and installs the wheel with pip, so each run of it takes about 25 s). Every one should be reported as caught. Left out on purpose: dropping the `__pycache__` test in
`package_files` (the `.py` name test beside it already leaves the compiled files out: an equivalent mutant) and dropping the check of Python 3.9 in run_editor.bat (the
tests run on a newer Python and cannot see it)."""
K = "dev/package.py"
A = "canopysynth/app.py"

AREAS = ["package", "app"]

MUTATIONS = [
    ("P01 the wheel is tagged for any platform", K, 'TAG = "py3-none-win_amd64"', 'TAG = "py3-none-any"'),
    ("P02 the wheel says it is pure Python", K, '"Root-Is-Purelib: false"', '"Root-Is-Purelib: true"'),
    ("P03 the DLL is left out of the package", K, '    files[NAME + "/canopysynth.dll"] = os.path.join(package, "canopysynth.dll")\n', ""),
    ("P04 a header is left out", K, 'HEADERS = ("canopy.h", "canopy_node.h", "canopy_engine.h")', 'HEADERS = ("canopy.h", "canopy_engine.h")'),
    ("P05 the import library is left out", K, '    files[NAME + "/lib/canopysynth.lib"] = os.path.join(ROOT, "build", "canopysynth.lib")\n', ""),
    ("P06 RECORD holds another hash", K, 'hashlib.sha256(data).digest()', 'hashlib.sha1(data).digest()'),
    ("P07 RECORD holds a wrong size", K, '{record_hash(data)},{len(data)}\\n"', '{record_hash(data)},{len(data) + 1}\\n"'),
    ("P08 a DLL of another build is accepted", K, "    if found != build:", "    if False:"),
    ("P09 the entry point names a function that does not exist", K, 'canopysynth-editor = canopysynth.app:main', 'canopysynth-editor = canopysynth.app:run'),
    ("P10 the long description is not the README", K, '        readme,\n    ]', '        "",\n    ]'),
    ("P11 the zip has no folder of its own inside", K, 'ZipInfo(top + "/" + os.path.relpath(source, folder)', 'ZipInfo(os.path.relpath(source, folder)'),
    ("P12 run_editor.bat is left out of the folder", K, '        "run_editor.bat": os.path.join(ROOT, "run_editor.bat"),\n', ""),
    ("P13 the built example DLL is left out of the folder", K, '        "examples/example_node.dll": os.path.join(ROOT, "build", "examples", "example_node.dll"),\n', ""),
    ("P14 the version and the delivery counter are read the wrong way round", K, "    return values[\"VERSION\"], values[\"CANOPYSYNTH_BUILD\"]", "    return values[\"CANOPYSYNTH_BUILD\"], values[\"VERSION\"]"),
    ("P15 the files carry the time of the day, not a fixed one", K, "FIXED_TIME = (2026, 1, 1, 0, 0, 0)", "FIXED_TIME = __import__('time').localtime()[:6]"),
    ("P16 the third-party notice is left out of the wheel", K, '    entries[f"{info}/licenses/THIRD_PARTY_NOTICES.txt"] = to_bytes(text_file(os.path.join(ROOT, "docs", "THIRD_PARTY_NOTICES.txt")))\n', ""),
    ("A01 a graph is written straight into its file, with no temporary file", A,
     '        with open(temporary, "w", encoding="utf-8", newline="\\n") as handle:\n            handle.write(text + "\\n")\n        os.replace(temporary, path)',
     '        with open(path, "w", encoding="utf-8", newline="\\n") as handle:\n            handle.write(text + "\\n")'),
    ("A02 saving does not clear the modified mark", A, "        self.path, self.modified = path, False\n        self._title()\n        return True", "        self.path = path\n        self._title()\n        return True"),
    ("A03 unsaved changes are never asked about", A, "        return not self.modified or self.confirm_discard()", "        return True"),
    ("A04 a graph the engine refuses to compile is not caught on opening", A, "        except (GraphError, BoundaryError, OSError) as error:\n            self.show_error(", "        except (GraphError, OSError) as error:\n            self.show_error("),
    ("A05 a new graph leaves the old engine running", A, "        self._release()\n        from .editor import Editor", "        from .editor import Editor"),
    ("A06 an edit does not mark the graph modified", A, "        if not self.modified:\n            self.modified = True\n            self._title()", "        pass"),
    ("A07 the command line says success when the file was refused", A, "            messagebox.showerror(\"CANOPY\", text)\n        return 1", "            messagebox.showerror(\"CANOPY\", text)\n        return 0"),
    ("A08 quitting leaves the engine open", A, "            self._release()\n            self.root.destroy()", "            self.root.destroy()"),
    ("A09 a file that is not JSON escapes as a ValueError", A, "        except ValueError as error:\n            raise GraphError(", "        except KeyError as error:\n            raise GraphError("),
    ("A10 a file given at the start is shown as a new, untitled graph", A, "            self._show(read_graph(path), path)\n\n    # ---- the graph on screen", "            self._show(read_graph(path), None)\n\n    # ---- the graph on screen"),
]
