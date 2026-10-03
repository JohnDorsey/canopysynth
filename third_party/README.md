# third_party

Vendored single-file libraries, kept byte for byte as downloaded (so these files have LF line endings, unlike the rest of the project).

| File | Version | Source | Bytes | SHA-256 | License |
|---|---|---|---|---|---|
| dr_wav.h | 0.14.6 (master, downloaded 2026-10-03, with the author's permission) | https://raw.githubusercontent.com/mackron/dr_libs/master/dr_wav.h | 369705 | 03e70c1a2d9787cd7ed3e966c075bea7bac6373f759db9cd7ca9ccdfc4ec4493 | public domain (Unlicense) or MIT-0, your choice; the text is at the end of the file |

`dr_wav.h` is compiled only in `src/canopy_fileread.c` (with `DR_WAV_IMPLEMENTATION`), through allocation callbacks that use `canopy_alloc`, with warnings 4701 and 4703 switched off around the include.
`miniaudio.h` will be added at plan step 7.
