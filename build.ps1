# SPDX-License-Identifier: GPL-3.0-or-later
# Builds canopysynth\canopysynth.dll (64-bit) and up to three test programs with MSVC (cl), found through vswhere:
#   build\examples\example_node.dll  the node type of examples\example_node.c (docs\node_author_guide.md), built against build\canopysynth.lib: it proves the example compiles
#   build\run_c_tests.exe        the C tests against the optimised library code
#   build\run_c_tests_debug.exe  the same tests against the MSVC debug runtime: /Od, /RTC1 (stack and uninitialised-variable checks),
#                                every heap operation validates the whole heap, leaked blocks are reported at the end
#   build\run_c_tests_asan.exe   the same tests under AddressSanitizer (/fsanitize=address): out-of-bounds reads and writes, use after free,
#                                with a report that names the line; built only when the "C++ AddressSanitizer" component is installed
#   powershell -ExecutionPolicy Bypass -File build.ps1
# With -Stress it builds, besides all that, the stand-alone stress program of plan step 13 (tests\stress\stress_main.c with tests\c\test_stress.c) in the
# same three flavours: build\stress.exe, build\stress_debug.exe and build\stress_asan.exe (see the head of tests\stress\stress_main.c for how to run them).
# With -Bench it builds build\bench.exe, the timing measurements of plan step 13 (tests\bench\bench_main.c with tests\c\support.c), optimised only (dev\measure.py runs it).
# Flags: C11 with C11 atomics, all warnings as errors, and /fp:precise (no fast-math: the determinism rule of docs\canopy_design.md section 5).
param([switch]$Stress, [switch]$Bench)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path $vswhere)) { throw "vswhere.exe not found: install Visual Studio 2022 with the C++ tools." }
$vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vs) { throw "No Visual Studio with the C++ x64 tools was found." }
$vcvars = Join-Path $vs "VC\Auxiliary\Build\vcvars64.bat"

$build = Join-Path $root "build"
$debugBuild = Join-Path $build "debug"
New-Item -ItemType Directory -Force -Path $build | Out-Null
New-Item -ItemType Directory -Force -Path $debugBuild | Out-Null
$sources = (Get-ChildItem (Join-Path $root "src") -Filter *.c | ForEach-Object { '"' + $_.FullName + '"' }) -join " "
$testSources = (Get-ChildItem (Join-Path $root "tests\c") -Filter *.c | ForEach-Object { '"' + $_.FullName + '"' }) -join " "
$common = "/nologo /std:c11 /experimental:c11atomics /W4 /WX /fp:precise /utf-8 /D_CRT_SECURE_NO_WARNINGS"
$flags = "$common /O2"
$debugFlags = "$common /Od /MDd /RTC1 /DCANOPY_DEBUG_HEAP"
$dll = Join-Path $root "canopysynth\canopysynth.dll"
$exe = Join-Path $build "run_c_tests.exe"
$exampleBuild = Join-Path $build "examples"
New-Item -ItemType Directory -Force -Path $exampleBuild | Out-Null
$exampleSource = Join-Path $root "examples\example_node.c"
$exampleDll = Join-Path $exampleBuild "example_node.dll"
$debugExe = Join-Path $build "run_c_tests_debug.exe"

$commands = @(
    "cl $flags /LD $sources /Fo`"$build\\`" /Fe`"$dll`" /link /IMPLIB:`"$build\canopysynth.lib`"",
    "cl $common /LD `"$exampleSource`" /I `"$root\src`" /Fo`"$exampleBuild\\`" /Fe`"$exampleDll`" `"$build\canopysynth.lib`"",
    "cl $flags $sources $testSources /Fo`"$build\\`" /Fe`"$exe`"",
    "cl $debugFlags $sources $testSources /Fo`"$debugBuild\\`" /Fe`"$debugExe`""
)

# AddressSanitizer: only if this Visual Studio has its x64 library and runtime (the "C++ AddressSanitizer" component). The runtime DLL is copied
# next to the test program so that it starts without the Visual Studio environment.
$asanExe = Join-Path $build "run_c_tests_asan.exe"
$msvc = Get-ChildItem (Join-Path $vs "VC\Tools\MSVC") -Directory | Sort-Object Name -Descending | Select-Object -First 1
$asanLib = Join-Path $msvc.FullName "lib\x64\libvcasan.lib"
$asanDll = Join-Path $msvc.FullName "bin\Hostx64\x64\clang_rt.asan_dynamic-x86_64.dll"
$haveAsan = (Test-Path $asanLib) -and (Test-Path $asanDll)
if ($haveAsan) {
    $asanBuild = Join-Path $build "asan"
    New-Item -ItemType Directory -Force -Path $asanBuild | Out-Null
    $asanFlags = "$common /Od /Zi /MD /fsanitize=address"
    $commands += "cl $asanFlags $sources $testSources /Fo`"$asanBuild\\`" /Fd`"$asanBuild\\vc.pdb`" /Fe`"$asanExe`" /link /INCREMENTAL:NO"
    Copy-Item $asanDll $build -Force
} elseif (Test-Path $asanExe) {
    Remove-Item $asanExe                      # an old build must not pass for the current code
}

if ($Stress) {
    $stressSources = '"' + (Join-Path $root "tests\c\support.c") + '" "' + (Join-Path $root "tests\c\test_stress.c") + '" "' + (Join-Path $root "tests\stress\stress_main.c") + '"'
    $stressBuild = Join-Path $build "stress"
    $stressDebugBuild = Join-Path $build "stress_debug"
    New-Item -ItemType Directory -Force -Path $stressBuild | Out-Null
    New-Item -ItemType Directory -Force -Path $stressDebugBuild | Out-Null
    $commands += "cl $flags $sources $stressSources /Fo`"$stressBuild\\`" /Fe`"$build\stress.exe`""
    $commands += "cl $debugFlags $sources $stressSources /Fo`"$stressDebugBuild\\`" /Fe`"$build\stress_debug.exe`""
    if ($haveAsan) {
        $stressAsanBuild = Join-Path $build "stress_asan"
        New-Item -ItemType Directory -Force -Path $stressAsanBuild | Out-Null
        $commands += "cl $asanFlags $sources $stressSources /Fo`"$stressAsanBuild\\`" /Fd`"$stressAsanBuild\\vc.pdb`" /Fe`"$build\stress_asan.exe`" /link /INCREMENTAL:NO"
    }
}

if ($Bench) {
    $benchBuild = Join-Path $build "bench"
    New-Item -ItemType Directory -Force -Path $benchBuild | Out-Null
    $benchSources = '"' + (Join-Path $root "tests\c\support.c") + '" "' + (Join-Path $root "tests\bench\bench_main.c") + '"'
    $commands += "cl $flags $sources $benchSources /Fo`"$benchBuild\\`" /Fe`"$build\bench.exe`""
}

foreach ($command in $commands) {
    cmd /c "`"$vcvars`" >nul && $command"
    if ($LASTEXITCODE -ne 0) { throw "Build failed: $command" }
}
if ($haveAsan) { Write-Host "built $dll, $exe, $debugExe and $asanExe" }
else { Write-Host "built $dll, $exe and $debugExe (AddressSanitizer is not installed: no sanitizer build)" }
if ($Bench) { Write-Host "built ${build}\bench.exe" }
if ($Stress) {
    $stressNames = "stress.exe, stress_debug.exe"
    if ($haveAsan) { $stressNames += ", stress_asan.exe" }
    Write-Host "built the stress programs in ${build}: $stressNames"
}
