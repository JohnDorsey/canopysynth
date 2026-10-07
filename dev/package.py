"""Makes the two distributions of plan step 14 from the built project: a wheel and an unzip-and-run folder (as a zip).

    python dev/package.py                  builds the DLL (build.ps1), then writes dist/canopysynth-1.0.0-py3-none-win_amd64.whl and
                                           dist/canopysynth-1.0.0-windows-x64.zip (and the folder it was made from, dist/canopysynth-1.0.0-windows-x64/)
    python dev/package.py --no-build        uses the DLL that is there (it must still be the one of this source: its build number is checked)
    python dev/package.py --out DIR         writes into DIR instead of dist/

The wheel: `pip install canopysynth-1.0.0-py3-none-win_amd64.whl` puts the package (with the DLL, the C headers and the import library) in site-packages and
adds a `canopysynth-editor` program. It is written here, by hand, with the standard library (a wheel is a zip file with a few text files in it: PEP 427),
so that making it needs no network and no build tools; `pip install` of the result is the test that it is a wheel (tests/python/test_package.py does it).
The folder: `run_editor.bat`, the package next to it (so `sys.path` can point at the folder, with no pip), the documents, the examples and the headers
and import library a C node author needs. Both hold the same `canopysynth/` package, staged once."""
import argparse
import base64
import ctypes
import hashlib
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

NAME = "canopysynth"
TAG = "py3-none-win_amd64"
FIXED_TIME = (2026, 1, 1, 0, 0, 0)               # every file in a zip gets this time, so that two runs on the same files make the same bytes
HEADERS = ("canopy.h", "canopy_node.h", "canopy_engine.h")           # what a C author needs (canopy_internal.h and canopy_core.h are not for hosts)
SUMMARY = "CANOPY: a node graph of audio and control values, with a C engine and a tkinter editor (Windows)"


def read_version():
    """(the release version, the delivery counter) from canopysynth/version.py, read as text so that nothing is imported."""
    values = {}
    with open(os.path.join(ROOT, "canopysynth", "version.py"), encoding="utf-8") as handle:
        for line in handle:
            for key in ("VERSION", "CANOPYSYNTH_BUILD"):
                if line.startswith(key + " = "):
                    values[key] = eval(line.split("=", 1)[1].split("#")[0].strip())
    return values["VERSION"], values["CANOPYSYNTH_BUILD"]


def check_dll(build):
    """Raises SystemExit unless the built DLL exists, is the delivery counter of this source and the import library is there."""
    dll = os.path.join(ROOT, "canopysynth", "canopysynth.dll")
    if not os.path.exists(dll):
        raise SystemExit(f"{dll} is not there: build it first (python run_tests.py, or powershell -File build.ps1)")
    lib = ctypes.CDLL(dll)
    lib.canopy_build_number.restype = ctypes.c_int32
    found = lib.canopy_build_number()
    if found != build:
        raise SystemExit(f"{dll} is build {found} but the source is build {build}: build again")
    with open(os.path.join(ROOT, "src", "canopy.h"), encoding="utf-8") as handle:
        header = [line.split()[-1] for line in handle if line.startswith("#define CANOPYSYNTH_BUILD")]
    if header != [str(build)]:
        raise SystemExit(f"src/canopy.h says build {header}, canopysynth/version.py says {build}")
    for path in (os.path.join(ROOT, "build", "canopysynth.lib"), os.path.join(ROOT, "build", "examples", "example_node.dll")):
        if not os.path.exists(path):
            raise SystemExit(f"{path} is not there: build again")


def package_files():
    """The files of the package as {path inside the package folder: path on disk}: the Python files, the DLL, the headers and the import library."""
    files = {}
    package = os.path.join(ROOT, "canopysynth")
    for folder, _dirs, names in os.walk(package):
        if "__pycache__" in folder:
            continue
        for name in names:
            if name.endswith(".py"):
                path = os.path.join(folder, name)
                files[NAME + "/" + os.path.relpath(path, package).replace(os.sep, "/")] = path
    files[NAME + "/canopysynth.dll"] = os.path.join(package, "canopysynth.dll")
    for header in HEADERS:
        files[f"{NAME}/include/{header}"] = os.path.join(ROOT, "src", header)
    files[NAME + "/lib/canopysynth.lib"] = os.path.join(ROOT, "build", "canopysynth.lib")
    return files


def text_file(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def to_bytes(text):
    """Text for a file of the wheel's .dist-info: UTF-8 with LF line endings, as the wheel standard has them (whatever the source file's)."""
    return text.replace("\r\n", "\n").encode("utf-8")


def read_bytes(path):
    with open(path, "rb") as handle:
        return handle.read()


def metadata(version):
    readme = text_file(os.path.join(ROOT, "README.md"))
    lines = [
        "Metadata-Version: 2.1",
        f"Name: {NAME}",
        f"Version: {version}",
        f"Summary: {SUMMARY}",
        "Requires-Python: >=3.9",
        "Classifier: Programming Language :: Python :: 3",
        "Classifier: Operating System :: Microsoft :: Windows",
        "Classifier: Topic :: Multimedia :: Sound/Audio",
        "Description-Content-Type: text/markdown",
        "",
        readme,
    ]
    return "\n".join(lines)


def wheel_file(version):
    return "\n".join(["Wheel-Version: 1.0", "Generator: canopysynth dev/package.py", "Root-Is-Purelib: false", f"Tag: {TAG}", ""])


ENTRY_POINTS = "[gui_scripts]\ncanopysynth-editor = canopysynth.app:main\n"


def record_hash(data):
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")


def write_wheel(files, version, out):
    """Writes the wheel and returns its path."""
    path = os.path.join(out, f"{NAME}-{version}-{TAG}.whl")
    info = f"{NAME}-{version}.dist-info"
    entries = {name: read_bytes(source) for name, source in sorted(files.items())}
    entries[f"{info}/METADATA"] = to_bytes(metadata(version))
    entries[f"{info}/WHEEL"] = to_bytes(wheel_file(version))
    entries[f"{info}/entry_points.txt"] = to_bytes(ENTRY_POINTS)
    entries[f"{info}/top_level.txt"] = to_bytes(NAME + "\n")
    entries[f"{info}/licenses/THIRD_PARTY_NOTICES.txt"] = to_bytes(text_file(os.path.join(ROOT, "docs", "THIRD_PARTY_NOTICES.txt")))
    record = "".join(f"{name},{record_hash(data)},{len(data)}\n" for name, data in entries.items()) + f"{info}/RECORD,,\n"
    entries[f"{info}/RECORD"] = record.encode("utf-8")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            member = zipfile.ZipInfo(name, FIXED_TIME)
            member.compress_type = zipfile.ZIP_DEFLATED
            member.external_attr = 0o644 << 16
            archive.writestr(member, data)
    return path


def make_folder(files, version, out):
    """Writes the unzip-and-run folder; returns its path."""
    folder = os.path.join(out, f"{NAME}-{version}-windows-x64")
    if os.path.exists(folder):
        shutil.rmtree(folder)
    for name, source in files.items():
        target = os.path.join(folder, *name.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(source, target)
    extras = {
        "run_editor.bat": os.path.join(ROOT, "run_editor.bat"),
        "README.md": os.path.join(ROOT, "README.md"),
        "docs/user_guide.md": os.path.join(ROOT, "docs", "user_guide.md"),
        "docs/node_author_guide.md": os.path.join(ROOT, "docs", "node_author_guide.md"),
        "docs/canopy_design.md": os.path.join(ROOT, "docs", "canopy_design.md"),
        "docs/THIRD_PARTY_NOTICES.txt": os.path.join(ROOT, "docs", "THIRD_PARTY_NOTICES.txt"),
        "examples/section15.py": os.path.join(ROOT, "examples", "section15.py"),
        "examples/example_node.c": os.path.join(ROOT, "examples", "example_node.c"),
        "examples/use_example_node.py": os.path.join(ROOT, "examples", "use_example_node.py"),
        "examples/example_node.dll": os.path.join(ROOT, "build", "examples", "example_node.dll"),
    }
    for name, source in extras.items():
        target = os.path.join(folder, *name.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(source, target)
    return folder


def zip_folder(folder):
    """Zips the folder (next to it, with a folder of the same name inside the zip) and returns the zip's path."""
    path = folder + ".zip"
    top = os.path.basename(folder)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for here, _dirs, names in os.walk(folder):
            for name in sorted(names):
                source = os.path.join(here, name)
                member = zipfile.ZipInfo(top + "/" + os.path.relpath(source, folder).replace(os.sep, "/"), FIXED_TIME)
                member.compress_type = zipfile.ZIP_DEFLATED
                member.external_attr = 0o644 << 16
                archive.writestr(member, read_bytes(source))
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description="make the wheel and the unzip-and-run folder")
    parser.add_argument("--no-build", action="store_true", help="do not run build.ps1 first")
    parser.add_argument("--out", default=os.path.join(ROOT, "dist"), help="where to write (default: dist/)")
    options = parser.parse_args(argv)
    version, build = read_version()
    if not options.no_build:
        result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", os.path.join(ROOT, "build.ps1")],
                                capture_output=True, text=True)
        if result.returncode != 0:
            raise SystemExit("the build failed:\n" + result.stdout + result.stderr)
    check_dll(build)
    os.makedirs(options.out, exist_ok=True)
    files = package_files()
    wheel = write_wheel(files, version, options.out)
    folder = make_folder(files, version, options.out)
    archive = zip_folder(folder)
    print(f"version {version} (build {build})")
    for path in (wheel, archive):
        print(f"  {path}  {os.path.getsize(path):,} bytes")
    print(f"  {folder}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
