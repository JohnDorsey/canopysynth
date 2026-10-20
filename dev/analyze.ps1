# SPDX-License-Identifier: GPL-3.0-or-later
# Runs MSVC's static analyzer (/analyze: buffer overruns, null pointers, uninitialised reads, leaks and the like) over every C source of the library,
# with the flags of build.ps1, and prints what it finds in our own files (src\). Nothing is built: the objects go to a scratch folder.
#   powershell -ExecutionPolicy Bypass -File dev\analyze.ps1
# Warnings located in the Windows SDK headers (annotation noise, C28301 and the like) and in the vendored third_party headers (dr_wav.h, miniaudio.h)
# are not ours to fix and are left out.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$installer = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer"
$vswhere = Join-Path $installer "vswhere.exe"
$vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vs) { throw "No Visual Studio with the C++ x64 tools was found." }
$vcvars = Join-Path $vs "VC\Auxiliary\Build\vcvars64.bat"
$scratch = Join-Path ([System.IO.Path]::GetTempPath()) "canopy_analyze"
New-Item -ItemType Directory -Force -Path $scratch | Out-Null
$env:PATH = "$env:PATH;$installer"                                                                         # (vcvars64.bat looks for vswhere on the path)
$common = "/nologo /std:c11 /experimental:c11atomics /W4 /fp:precise /utf-8 /D_CRT_SECURE_NO_WARNINGS"      # (no /WX: the point is to see every warning)
$sources = Get-ChildItem (Join-Path $root "src") -Filter *.c
$ownFiles = [regex]::Escape((Join-Path $root "src"))
$total = 0
foreach ($source in $sources) {
    $output = cmd /c "`"$vcvars`" >nul 2>&1 && cl $common /O2 /analyze /c `"$($source.FullName)`" /Fo`"$scratch\\`" 2>&1"
    $ours = @($output | Where-Object { $_ -match "^$ownFiles.*warning C\d+" } | Sort-Object -Unique)
    Write-Host ("{0,-22} {1} warning(s)" -f $source.Name, $ours.Count)
    $ours | ForEach-Object { Write-Host "    $_" }
    $total += $ours.Count
}
Write-Host "analyzed $(@($sources).Count) files: $total warning(s) in our own code"
