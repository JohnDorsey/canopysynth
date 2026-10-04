# third_party

Vendored single-file libraries, kept byte for byte as downloaded (so these files have LF line endings, unlike the rest of the project).

| File | Version | Source | Bytes | SHA-256 | License |
|---|---|---|---|---|---|
| dr_wav.h | 0.14.6 (master, downloaded 2026-10-03, with the author's permission) | https://raw.githubusercontent.com/mackron/dr_libs/master/dr_wav.h | 369705 | 03e70c1a2d9787cd7ed3e966c075bea7bac6373f759db9cd7ca9ccdfc4ec4493 | public domain (Unlicense) or MIT-0, your choice; the text is at the end of the file |

| miniaudio.h | 0.11.25 (tag 0.11.25, released 2026-03-03, downloaded 2026-10-03, with the author's permission) | https://raw.githubusercontent.com/mackron/miniaudio/0.11.25/miniaudio.h | 4108168 | ac7af4de748b7e26b777f37e01cee313a308a7296a3eb080e2906b320cc55c89 | public domain (Unlicense) or MIT-0, your choice; the text is at the end of the file |

`dr_wav.h` is compiled only in `src/canopy_fileread.c` (with `DR_WAV_IMPLEMENTATION`), through allocation callbacks that use `canopy_alloc`, with warnings 4701 and 4703 switched off around the include.

`miniaudio.h` is compiled only in `src/canopy_audio.c` (with `MINIAUDIO_IMPLEMENTATION`), with decoding, encoding, generation, the resource manager, the node graph and the engine of miniaudio switched off and only two audio systems enabled: WASAPI (the operating system's, on Windows) and the null backend (which takes audio in real time and plays it nowhere: for tests and for hosts without sound hardware). Its allocations go through `canopy_alloc_unhooked`; see "Found on the way" in the plan's step 7 decisions for why the tests' failure hook does not reach them. Warnings are switched off around the include.
