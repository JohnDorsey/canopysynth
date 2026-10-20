# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests: the two distributions of plan step 14 (dev/package.py): the wheel is a real wheel (pip installs it into a fresh virtual environment, the section 15 program
runs there, from another folder), the folder runs unzipped (run_editor.bat, `sys.path`, the example node), and the example node of the node author guide
compiles with the command the guide gives. The packages are made once, in a temporary folder, from the DLL and files the earlier tests use."""
import atexit
import base64
import csv
import hashlib
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "dev"))
import package                                                         # noqa: E402

VERSION, BUILD = package.read_version()
WHEEL_NAME = f"canopysynth-{VERSION}-py3-none-win_amd64.whl"
FOLDER_NAME = f"canopysynth-{VERSION}-windows-x64"
_made = {}


def made():
    """Makes the packages once: {"out", "wheel", "zip", "folder"}."""
    if not _made:
        out = tempfile.mkdtemp(prefix="canopy_package_")
        atexit.register(shutil.rmtree, out, True)
        assert package.main(["--no-build", "--out", out]) == 0
        _made.update(out=out, wheel=os.path.join(out, WHEEL_NAME), zip=os.path.join(out, FOLDER_NAME + ".zip"), folder=os.path.join(out, FOLDER_NAME))
    return _made


def run(command, **options):
    options.setdefault("timeout", 120)
    return subprocess.run(command, capture_output=True, text=True, **options)


def source_bytes(path):
    with open(os.path.join(ROOT, *path.split("/")), "rb") as handle:
        return handle.read()


def test_py_the_wheel_has_the_package_the_dll_the_headers_and_correct_metadata_and_every_record_hash_matches():
    with zipfile.ZipFile(made()["wheel"]) as wheel:
        names = wheel.namelist()
        info = f"canopysynth-{VERSION}.dist-info"
        for needed in ("canopysynth/__init__.py", "canopysynth/__main__.py", "canopysynth/app.py", "canopysynth/engine.py", "canopysynth/editor/canvas.py",
                       "canopysynth/canopysynth.dll", "canopysynth/include/canopy.h", "canopysynth/include/canopy_node.h", "canopysynth/include/canopy_engine.h",
                       "canopysynth/lib/canopysynth.lib", f"{info}/METADATA", f"{info}/WHEEL", f"{info}/RECORD", f"{info}/entry_points.txt",
                       f"{info}/licenses/THIRD_PARTY_NOTICES.txt", f"{info}/licenses/LICENSE"):
            assert needed in names, (needed, names)
        assert wheel.read(f"{info}/licenses/LICENSE") == source_bytes("LICENSE").replace(b"\r\n", b"\n")
        assert not [n for n in names if "__pycache__" in n or n.endswith(".pyc") or n.startswith("tests") or n.startswith("dev")], names
        assert wheel.read("canopysynth/canopysynth.dll") == source_bytes("canopysynth/canopysynth.dll")
        assert wheel.read("canopysynth/version.py") == source_bytes("canopysynth/version.py")
        wheel_text = wheel.read(f"{info}/WHEEL").decode()
        assert "Tag: py3-none-win_amd64" in wheel_text and "Root-Is-Purelib: false" in wheel_text and "Wheel-Version: 1.0" in wheel_text, wheel_text
        meta = wheel.read(f"{info}/METADATA").decode()
        for line in ("Metadata-Version: 2.1", "Name: canopysynth", f"Version: {VERSION}", "Requires-Python: >=3.9", "Operating System :: Microsoft :: Windows",
                     "License: GPL-3.0-or-later", "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)"):
            assert line in meta, line
        assert "# CANOPY" in meta                                       # the README is the long description
        assert "canopysynth-editor = canopysynth.app:main" in wheel.read(f"{info}/entry_points.txt").decode()
        rows = list(csv.reader(io.StringIO(wheel.read(f"{info}/RECORD").decode())))
        listed = {row[0]: row for row in rows}
        assert set(listed) == set(names) and len(rows) == len(names), "RECORD does not list exactly the files of the wheel"
        for name in names:
            if name.endswith("/RECORD"):
                assert listed[name][1:] == ["", ""]
                continue
            data = wheel.read(name)
            digest = "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
            assert listed[name][1] == digest and listed[name][2] == str(len(data)), name


def test_py_making_the_packages_twice_gives_the_same_bytes_and_every_file_has_the_fixed_time():
    for name in (WHEEL_NAME, FOLDER_NAME + ".zip"):                        # (two runs in the same second would hide a time of the day)
        with zipfile.ZipFile(os.path.join(made()["out"], name)) as archive:
            assert {member.date_time for member in archive.infolist()} == {(2026, 1, 1, 0, 0, 0)}, name
    out = tempfile.mkdtemp(prefix="canopy_package_again_")
    try:
        assert package.main(["--no-build", "--out", out]) == 0
        for name in (WHEEL_NAME, FOLDER_NAME + ".zip"):
            with open(os.path.join(out, name), "rb") as again, open(os.path.join(made()["out"], name), "rb") as first:
                assert again.read() == first.read(), name
    finally:
        shutil.rmtree(out, ignore_errors=True)


def test_py_the_folder_has_run_editor_bat_the_package_the_documents_and_the_examples_and_the_zip_holds_the_same_files():
    folder = made()["folder"]
    expected = ["run_editor.bat", "README.md", "LICENSE", "canopysynth/canopysynth.dll", "canopysynth/__init__.py", "canopysynth/include/canopy_node.h", "canopysynth/lib/canopysynth.lib",
                "docs/user_guide.md", "docs/node_author_guide.md", "docs/canopy_design.md", "docs/THIRD_PARTY_NOTICES.txt", "examples/section15.py",
                "examples/example_node.c", "examples/use_example_node.py", "examples/example_node.dll"]
    for name in expected:
        assert os.path.isfile(os.path.join(folder, *name.split("/"))), name
    assert source_bytes("run_editor.bat") == open(os.path.join(folder, "run_editor.bat"), "rb").read()
    with zipfile.ZipFile(made()["zip"]) as archive:
        inside = sorted(archive.namelist())
        on_disk = sorted(f"{FOLDER_NAME}/" + os.path.relpath(os.path.join(here, n), folder).replace(os.sep, "/")
                         for here, _d, names in os.walk(folder) for n in names)
        assert inside == on_disk
        assert archive.read(f"{FOLDER_NAME}/canopysynth/canopysynth.dll") == source_bytes("canopysynth/canopysynth.dll")


def test_py_a_dll_that_is_not_the_build_of_the_source_is_refused_before_anything_is_written():
    try:
        package.check_dll(BUILD + 1)
    except SystemExit as stop:
        assert f"build {BUILD}" in str(stop) and f"build {BUILD + 1}" in str(stop), str(stop)
    else:
        raise AssertionError("a DLL of another build was accepted")


def test_py_pip_installs_the_wheel_into_a_fresh_environment_and_the_section_15_program_runs_there_from_another_folder():
    with tempfile.TemporaryDirectory() as work:
        environment = os.path.join(work, "env")
        assert run([sys.executable, "-m", "venv", "--without-pip", environment]).returncode == 0
        python = os.path.join(environment, "Scripts", "python.exe")
        result = run([sys.executable, "-m", "pip", "--python", python, "install", "--no-index", "--no-deps", made()["wheel"]])
        assert result.returncode == 0, result.stdout + result.stderr
        site = os.path.join(environment, "Lib", "site-packages")
        assert os.path.isfile(os.path.join(site, "canopysynth", "canopysynth.dll"))
        assert os.path.isfile(os.path.join(site, "canopysynth", "include", "canopy_node.h"))
        assert os.path.isfile(os.path.join(environment, "Scripts", "canopysynth-editor.exe")), os.listdir(os.path.join(environment, "Scripts"))
        elsewhere = os.path.join(work, "elsewhere")
        os.mkdir(elsewhere)
        shutil.copyfile(os.path.join(ROOT, "examples", "section15.py"), os.path.join(elsewhere, "section15.py"))
        probe = run([python, "-c", "import canopysynth; print(canopysynth.__file__); print(canopysynth.__version__)"], cwd=elsewhere)
        assert probe.returncode == 0, probe.stderr
        lines = probe.stdout.split("\n")
        assert os.path.normcase(os.path.join(site, "canopysynth")) in os.path.normcase(lines[0]), lines     # the installed copy, not the source tree
        assert lines[1] == VERSION
        program = run([python, "section15.py", "--no-window"], cwd=elsewhere)
        assert program.returncode == 0 and program.stdout.rstrip().endswith("ok"), program.stdout + program.stderr
        assert "song_left outlet" in program.stdout and "480 samples" in program.stdout
        module = run([python, "-m", "canopysynth", "--help"], cwd=elsewhere)
        assert module.returncode == 0 and "--audio" in module.stdout, module.stderr
        uninstall = run([sys.executable, "-m", "pip", "--python", python, "uninstall", "-y", "canopysynth"])
        assert uninstall.returncode == 0 and not os.path.exists(os.path.join(site, "canopysynth", "canopysynth.dll")), uninstall.stdout + uninstall.stderr


def test_py_the_unzipped_folder_runs_by_sys_path_by_run_editor_bat_and_with_the_shipped_example_node():
    with tempfile.TemporaryDirectory() as work:
        with zipfile.ZipFile(made()["zip"]) as archive:
            archive.extractall(work)
        folder = os.path.join(work, FOLDER_NAME)
        elsewhere = os.path.join(work, "elsewhere")
        os.mkdir(elsewhere)
        code = f"import sys; sys.path.insert(0, {folder!r}); import canopysynth; print(canopysynth.__file__); canopysynth.Engine(canopysynth.Graph()).close(); print('ok')"
        probe = run([sys.executable, "-c", code], cwd=elsewhere)
        assert probe.returncode == 0 and probe.stdout.split("\n")[1] == "ok", probe.stderr
        assert os.path.normcase(folder) in os.path.normcase(probe.stdout.split("\n")[0])
        section = run([sys.executable, os.path.join(folder, "examples", "section15.py"), "--no-window"], cwd=elsewhere)
        assert section.returncode == 0 and section.stdout.rstrip().endswith("ok"), section.stdout + section.stderr
        node = run([sys.executable, os.path.join(folder, "examples", "use_example_node.py")], cwd=elsewhere)
        assert node.returncode == 0 and node.stdout.rstrip().endswith("ok"), node.stdout + node.stderr
        environment = dict(os.environ, CANOPY_CONSOLE="1")
        environment.pop("PYTHONPATH", None)
        helped = run(["cmd", "/c", os.path.join(folder, "run_editor.bat"), "--help"], cwd=elsewhere, env=environment)
        assert helped.returncode == 0 and "--audio" in helped.stdout, helped.stdout + helped.stderr
        bad = os.path.join(elsewhere, "bad file.json")                        # (a name with a space: dropping a file on the batch file passes it quoted)
        with open(bad, "w") as handle:
            handle.write("not a graph")
        refused = run(["cmd", "/c", os.path.join(folder, "run_editor.bat"), bad, "--audio", "null"], cwd=elsewhere, env=environment)
        assert refused.returncode == 1 and "could not be opened" in refused.stderr and "bad file.json" in refused.stderr, refused.stdout + refused.stderr


def vcvars():
    vswhere = os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Microsoft Visual Studio", "Installer", "vswhere.exe")
    studio = run([vswhere, "-latest", "-products", "*", "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"]).stdout.strip()
    assert studio, "no Visual Studio with the C++ tools"
    return os.path.join(studio, "VC", "Auxiliary", "Build", "vcvars64.bat")


def test_py_the_example_node_compiles_in_the_unzipped_folder_with_the_command_the_guide_gives_and_the_result_works():
    with open(os.path.join(ROOT, "docs", "node_author_guide.md"), encoding="utf-8") as handle:
        commands = [line.strip() for line in handle if line.startswith("cl /nologo")]
    assert len(commands) == 1, commands
    command = commands[0]
    assert "/I canopysynth\\include" in command and "canopysynth\\lib\\canopysynth.lib" in command and "examples\\example_node.c" in command, command
    with tempfile.TemporaryDirectory() as work:
        with zipfile.ZipFile(made()["zip"]) as archive:
            archive.extractall(work)
        folder = os.path.join(work, FOLDER_NAME)
        os.remove(os.path.join(folder, "examples", "example_node.dll"))                           # the shipped one is not what is tested here
        script = os.path.join(work, "compile.bat")
        with open(script, "w") as handle:
            handle.write(f'@echo off\r\ncall "{vcvars()}" >nul\r\ncd /d "{folder}"\r\n{command}\r\n')
        built = run(["cmd", "/c", script], cwd=work)
        assert built.returncode == 0 and os.path.isfile(os.path.join(folder, "examples", "example_node.dll")), built.stdout + built.stderr
        assert "warning" not in built.stdout.lower(), built.stdout
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        used = run([sys.executable, os.path.join(folder, "examples", "use_example_node.py")], cwd=work, env=environment)
        assert used.returncode == 0 and used.stdout.rstrip().endswith("ok"), used.stdout + used.stderr


def pe_imports(path):
    """The names of the DLLs a 64-bit PE file imports (the import table of its header: what the loader needs before the file runs)."""
    import struct
    with open(path, "rb") as handle:
        data = handle.read()
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    assert data[pe:pe + 4] == b"PE\0\0"
    sections, optional_size = struct.unpack_from("<H", data, pe + 6)[0], struct.unpack_from("<H", data, pe + 20)[0]
    optional = pe + 24
    assert struct.unpack_from("<H", data, optional)[0] == 0x20B, "not a 64-bit file"
    import_rva = struct.unpack_from("<I", data, optional + 112 + 8)[0]
    table = optional + optional_size
    layout = [struct.unpack_from("<IIII", data, table + 40 * k + 8) for k in range(sections)]       # VirtualSize, VirtualAddress, RawSize, RawPointer

    def offset(rva):
        for size, address, _raw, pointer in layout:
            if address <= rva < address + max(size, _raw):
                return rva - address + pointer
        raise AssertionError(f"RVA {rva:#x} is in no section")

    names, at = [], offset(import_rva)
    while any(data[at:at + 20]):
        name_rva = struct.unpack_from("<I", data, at + 12)[0]
        start = offset(name_rva)
        names.append(data[start:data.index(b"\0", start)].decode().lower())
        at += 20
    return names


def test_py_the_dll_imports_only_kernel32_so_no_visual_cpp_redistributable_is_needed():
    assert pe_imports(os.path.join(ROOT, "canopysynth", "canopysynth.dll")) == ["kernel32.dll"]
    assert pe_imports(sys.executable) != [], "the reader finds the imports of a file that has some"
