<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Portability inventory: everything in canopysynth that is Windows- or MSVC-specific

Written 2026-10-22 (delivery counter 21 → 22), before any port. It is a list of work, not a plan: no source file was changed to make it. The method was `grep` over `src/`,
`tests/`, `dev/`, `canopysynth/` and the scripts, then reading every hit; the counts below are what the greps printed. **FOUND** means a line of code was read. **BELIEVED**
means reasoned from reading, not tried (nothing here was ever compiled with another compiler for another operating system; step 14b only built the C tests with clang
on Windows). The sizes (S, M, L) are my guesses at the work, in the unit of a focused session: S under an hour, M a few hours, L most of a day.

What the author decided earlier: the platform is Windows (plan step 0, rule R7, the "Platform" line of `CLAUDE.md`). **The design document does not say so**: its one
mention of MSVC is the remark that it has no 128-bit integers (section 4). Making the project portable therefore changes plan rules, not the design, except where marked
"design-visible" below.

## 1. The engine (`src/`): small

| # | What | Where (FOUND) | What a port needs | Size |
|---|---|---|---|---|
| E1 | The engine's lock is a Windows slim reader/writer lock | `canopy_core.h:9-27` (`typedef SRWLOCK CanopyLock` and four inline wrappers; a hard `#error` for any other platform); `canopy_engine.c:418-420` calls `InitializeSRWLock` three times, bypassing the wrappers; `canopy_audio.c:38` has a second `SRWLOCK audio_lock` and calls `AcquireSRWLockExclusive` / `ReleaseSRWLockExclusive` directly at lines 145, 160, 217, 273, 280, 289, 292 | A complete wrapper (init, shared, exclusive) over `pthread_rwlock_t` elsewhere, and every direct call moved behind it. The design's locking promises (exclusive waits for shared; queries never take it) must hold with the other implementation: BELIEVED that `pthread_rwlock` can do it, but its fairness differs from SRW, and the lock tests in `test_swap.c` and `test_service.c` are the check | S to M |
| E2 | Export of the C API | `canopy.h:8-9`: `#define CANOPY_API __declspec(dllexport)` under `_WIN32` | `__attribute__((visibility("default")))` and `-fvisibility=hidden`; the export-table test (`test_c_api.py`, `pe_exports`) reads the exports with a Python parser of the Windows PE file format, so it needs an ELF / Mach-O reader or `nm -D` / `nm -gU` | S to M |
| E3 | MSVC warning pragmas | `canopy_audio.c:20-33` and `canopy_fileread.c:18-22` (`#pragma warning`, around the vendored headers) | Guard with `_MSC_VER`; other compilers need their own way to silence warnings from `third_party/` (or none, if they are clean) | S |
| E4 | **The file node knows only Windows paths and Windows file APIs** | `canopy_fileread.c:63-69` `absolute_path()` accepts only `C:\x`, `C:/x` and `\\host\share`; `:88-90` `MultiByteToWideChar(CP_UTF8, ...)`; `GetFileAttributesW`; `drwav_init_file_w`. The same rule is written again in `canopysynth/_values.py:14-20` (`is_absolute_path`), and a test compares the two | An absolute path on POSIX is one that starts with `/`; a UTF-8 path can be opened directly (`drwav_init_file` or `fopen` + `stat`). **Design-visible**: design sections 11 and 14 say the path is stored absolute, and a graph saved on Windows (`C:\audio\song.wav`) opened on Linux would name a file that cannot exist. What the node should do then (refuse, with the existing message? try the path with its drive removed?) is the author's decision. The Python and C rules must stay equal | M |
| E5 | Audio backend | `canopy_audio.c:29` `#define MA_ENABLE_WASAPI`, `:105` `ma_backend_wasapi`; `MA_ENABLE_ONLY_SPECIFIC_BACKENDS` with only WASAPI and null | Add CoreAudio (macOS) and ALSA, PulseAudio (Linux) to the enabled list and choose by platform; link flags (`-ldl -lpthread -lm`, and on macOS the frameworks miniaudio uses, BELIEVED to be loaded at run time, not linked). The tests use the null backend only, so a CI runner needs no sound device | S to M |
| E6 | C11 atomics | `<stdatomic.h>` in `canopy_alloc.c`, `canopy_audio.c`, `canopy_preview.c`, `canopy_core.h`, `canopy_internal.h`; `build.ps1` needs `/experimental:c11atomics` for MSVC | Nothing: gcc and clang have them. A point in favour of porting | none |

Checked and **not** a problem (FOUND by grep): no `sin`, `cos`, `exp`, `log`, `pow` or other libm function is called anywhere in `src/` (the only match is a comment), so
the engine's arithmetic is `+ - * /` and `floor` on IEEE floats; there is no 128-bit integer (rule); `src/` writes 64-bit values as `long long` and `%lld` (the width of
`long` differs between Windows and Linux, and `src/` avoids it); `strdup` is the project's own `canopy_pool_strdup`.

## 2. The C tests, the stress program and the benchmark (`tests/c`, `tests/stress`, `tests/bench`): many sites, mechanical

15 files include `<windows.h>`. The kinds of call (counts of uses, FOUND by grep):

| Call | Uses | What it is for | Portable replacement |
|---|---|---|---|
| `Sleep` | 38 | pacing, waiting | `nanosleep` / `usleep` or a shim |
| `_beginthreadex`, `WaitForSingleObject`, `WaitForMultipleObjects`, `CloseHandle` | 26, 11, 8, 19 | the test threads | `pthread_create` / `join`, or C11 `<threads.h>` (BELIEVED not available on every platform's libc: macOS had none for a long time) |
| `InterlockedIncrement` | 21 | counters | C11 `atomic_fetch_add` |
| `GetTickCount64`, `QueryPerformanceCounter`, `QueryPerformanceFrequency` | 26, 5, 3 | timing | `clock_gettime(CLOCK_MONOTONIC)` |
| `GetTempPathA`, `DeleteFileA` | 6, 5 | scratch WAV files | `mkstemp`, `unlink` |
| `_CrtSetReportMode`, `_CrtSetDbgFlag`, `_CrtDumpMemoryLeaks`, `_CrtCheckMemory` | 6, 2, 2, 2 | the MSVC **debug heap** run (`run_c_tests_debug.exe`) | no equivalent; that run is replaced by AddressSanitizer plus LeakSanitizer (and `valgrind` on Linux) |
| `_aligned_malloc` | 1 | alignment | `aligned_alloc` / `posix_memalign` |

The cleanest way is one small header (say `tests/c/portable.h`: thread, sleep, tick, atomic add, temp file) used by all 15 files, so that the platform code is in one place. Size M.
The `long` / `%ld` family also appears in the tests (133 lines in 18 files; most are `long long`, BELIEVED, not each one read): worth one pass for the 32-bit-`long` assumption.

## 3. Build, test runner and tools: Windows only, one script each

| # | What | Where (FOUND) | What a port needs | Size |
|---|---|---|---|---|
| B1 | The build is `build.ps1` | finds Visual Studio with `vswhere`, runs `vcvars64.bat`; flags `/std:c11 /experimental:c11atomics /W4 /WX /fp:precise /utf-8 /D_CRT_SECURE_NO_WARNINGS`; AddressSanitizer is `/fsanitize=address` with the runtime DLL copied beside the program | A second script, or one cross-platform build (a Python script, a Makefile or CMake; none exists). The equivalent flags are `-std=c11 -Wall -Wextra -Werror -ffp-contract=off -fno-fast-math -fvisibility=hidden` and `-fsanitize=address,undefined` | M |
| B2 | `run_tests.py` | runs `powershell ... build.ps1` (`:45`), then `build\run_c_tests.exe`, `..._debug.exe`, `..._asan.exe` by name (`:67-101`) | Choose the build command and the file names by platform; the debug-heap run is skipped where it does not exist (the runner already skips it when the file is missing) | S |
| B3 | Static analysis | `dev/analyze.ps1` (`cl /analyze`) | none needed; `clang-tidy` or `cppcheck` could be added later | none |
| B4 | The mutation runner and `dev/measure.py`, `dev/stress.py`, `dev/listen_check.py`, `dev/editor_check.py` | `mutate.py` calls `run_tests.py` (`:52`) and also runs `powershell ... build.ps1` itself (`:76`), so it needs the same platform choice as B2; the copy of the project for a campaign is made with `robocopy` by hand (a rule in `CLAUDE.md`, not code); `measure.py` looks for `build\bench.exe` (`:22`, `:187`) | Mostly follows B1 and B2; check each script | S to M |

## 4. The Python package: small

| # | What | Where (FOUND) | What a port needs | Size |
|---|---|---|---|---|
| P1 | The library's file name | `canopysynth/_lib.py:8` `DLL_PATH = ... "canopysynth.dll"` and two error messages that name it; `build.ps1` and `dev/package.py` write and collect `canopysynth.dll` | `.dll`, `.so` or `.dylib` by `sys.platform`; `ctypes.CDLL` itself is portable | S |
| P2 | Absolute paths | `_values.py:14-20` (see E4) | follows E4 | S |
| P3 | Launchers | `run_editor.bat` (uses `py -3`, `pyw -3`, a batch-file `%errorlevel%` rule); `app.py:174` has a case for `pythonw` having no console | a shell launcher for the other systems; the package itself (`python -m canopysynth`) is portable. `tkinter` file dialogs are portable | S |
| P4 | tkinter | all of `canopysynth/editor/` | Nothing found that is Windows-only (FOUND: no `-alpha`, `-topmost`, `iconbitmap`, no Windows-specific window call). BELIEVED: behaviour of Tk differs in details (mouse wheel events, right-button numbers on macOS, the `Alt` key), and the editor's wheel and pan code was only tried on Windows | S to M |

## 5. The Python tests: the larger part

Windows-specific references per file (FOUND, a count of lines that mention a `.dll`, `.exe`, `.bat`, `win_amd64`, a job object, `KERNEL32` and similar):
`test_package.py` 33, `test_runner.py` 16, `test_graph.py` 15, `test_shutdown.py` 14, `test_bridge.py` 9, `test_editor.py` 4, `test_editor_link.py` 3, `test_app.py` 3, and one or two in ten more files; `dev/package.py` 12.

- `test_package.py`: the wheel's tag, `.dll`, `run_editor.bat`, and the test that the DLL imports only `KERNEL32.dll` (`pe_imports`, a Python reader of the Windows PE format; the packages promise no redistributable). On other systems the equivalent promise is "links only libc, libm and libpthread" (`ldd`, `otool -L`).
- `test_shutdown.py`: the out-of-memory tests limit the child with a Windows **job object** through `ctypes` (`CreateJobObject`). Linux has `RLIMIT_AS` (`resource.setrlimit`); BELIEVED that macOS does not enforce it, so those tests would be skipped there. Also see "A flaky test" in the plan: the instance-limit test is intermittently flaky even on Windows.
- `test_graph.py`, `test_bridge.py`: mostly Windows path strings (`C:\...`) used as test data, BELIEVED harmless, not each read.
- Every editor test opens a real Tk window placed at `+6000+6000` (7 files). That works on Windows. BELIEVED: Linux needs a virtual display (`xvfb-run`), and macOS may move a window that is off the screen back onto it, which would make the "off-screen, nothing flashes" trick show a window, though not break the tests.
- `test_runner.py` builds a throwaway project with stub `.exe` programs.

A way to keep this small: mark the platform-specific tests with a skip condition and write the other platform's version beside them, rather than make one test fit all.

## 6. Packaging and documents

- `dev/package.py` writes a wheel by hand with the tag `py3-none-win_amd64` and the DLL, header files and import library (`.lib`) inside. Another platform needs its own tag (`macosx_11_0_arm64`, `manylinux_2_28_x86_64`) and no import library. BELIEVED: a manylinux wheel built on a CI runner is not accepted by PyPI without being built in the manylinux container (or repaired with `auditwheel`); a macOS wheel built on a runner would be tagged for that runner's OS version. Until then, "build from source" is the honest instruction for other systems.
- Text that says Windows only: `README.md` (1), `docs/user_guide.md` (2), `docs/node_author_guide.md` (1), `CLAUDE.md` (5), the plan (39); the design 0 (see above).

## 7. Determinism on other compilers and CPUs (the one risk that is not a line of code)

- FOUND (step 14b, run): clang 19 on Windows gives the same bits as MSVC for the twelve recorded graphs when told `-ffp-contract=off`; letting the compiler fuse multiply-add changes them, and the determinism test fails loudly.
- BELIEVED, not run: gcc fuses multiply-add by default in GNU C mode (`-ffp-contract=fast`), and clang on Apple Silicon (hardware FMA) may fuse within an expression by default; both need `-ffp-contract=off` explicitly. An ARM CPU has no x87 or other extended-precision surprises, but flush-to-zero of denormals depends on the OS's default mode, BELIEVED off for ordinary user code.
- **The engine has no libm calls (section 1), so it can be bit-identical everywhere; the `std.` node library will have them** (oscillators, filters, envelope followers use `sin`, `exp`, `pow`). MSVC's, glibc's and Apple's libm do not promise the same last bit. Before any `std.` node that calls libm is written, the author needs to choose: (a) the project's own deterministic implementations of the few functions it needs, (b) one table of recorded hashes per platform, or (c) "exact on one platform, within a stated tolerance across platforms" for those nodes. This is the decision that is most expensive to make late.

## 8. What stage 1 (this change) does and does not do

Does: adds `.github/workflows/ci.yml`, which builds and runs the whole suite on a clean GitHub-hosted Windows machine with MSVC (as the project's one supported setup), the
Python-only tests on the other Python versions the wheel claims (`Requires-Python >=3.9`), and keeps the wheel and zip made by the full job as downloadable files. Adds
`tests/python/test_ci.py`, which fails if the workflow stops covering the oldest Python the package claims.
Does not: change any source, build or test file to run elsewhere; run on Linux or macOS. The workflow has not been run (there is no remote yet): its first run on the
author's new repository is the first test of it.

## 9. Suggested order (the author decides)

1. The workflow of stage 1 on Windows, on a branch, until it is green. **Expect adjustments**: nothing in it has run on a runner yet.
2. Decide the platform scope in the plan (R7, step 0 and `CLAUDE.md` say Windows) and the file-path question (E4), because both change what "done" means.
3. Linux with gcc and clang (E1-E3, E5, B1-B2, P1, the test header of section 2), in CI on `ubuntu-latest`; WSL on the author's machine can serve as a quicker loop (BELIEVED installed: `Program Files\WSL` is on the PATH; no distribution was looked for).
4. The determinism decision of section 7, before the `std.` library grows.
5. macOS (arm64): CoreAudio, Tk differences, and whichever of the tests turn out to depend on the scheduler.
