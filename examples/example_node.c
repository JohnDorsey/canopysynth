/* SPDX-License-Identifier: GPL-3.0-or-later */
/* A node type written by someone other than the engine's authors: the worked example of docs/node_author_guide.md.

   "example.scale" has two inlets, `in` (the signal) and `gain` (default knob position 0.5), one outlet, `out`, and one setting, `offset`:
       out = in * gain + offset
   It implements both queries (a span is done in one pass, which is faster than n point queries), is flagged realtime safe (it allocates nothing
   and takes no lock), and asks the engine for one scratch buffer.

   Build (from a "x64 Native Tools Command Prompt for VS", in the folder of the distribution; build.ps1 does the same in a source checkout):
       cl /nologo /std:c11 /W4 /fp:precise /LD examples\example_node.c /I canopysynth\include /Fe:examples\example_node.dll canopysynth\lib\canopysynth.lib
   (/fp:precise and no fast-math: a node's arithmetic must give the same bits every time, design section 5.)

   Use: examples\use_example_node.py loads the DLL and registers the type. The one exported function, canopy_example_register, is this file's own;
   it is what a host calls on the registry it made. */
#include "canopy_node.h"

enum { INLET_IN = 0, INLET_GAIN = 1 };
enum { SETTING_OFFSET = 0 };

/* ---- the two queries ----
   A handler never branches on whether an inlet is connected: canopy_inlet_at and canopy_inlet_span give the connected outlet's answer, or the
   inlet's knob position when nothing is connected. Both pass the upstream status through, and a node that returns it unchanged is doing what is
   expected (after a nonzero status the engine ignores what `out` holds: a point is 0.0 and a span is zero-filled). */

static int32_t scale_at(CanopyCtx *ctx, int32_t outlet, int64_t t, float *out)
{
    float in, gain;
    int32_t status;
    (void)outlet;                                       /* there is only one outlet */
    status = canopy_inlet_at(ctx, INLET_IN, t, &in);
    if (status != CANOPY_OK) return status;
    status = canopy_inlet_at(ctx, INLET_GAIN, t, &gain);
    if (status != CANOPY_OK) return status;
    *out = (float)((double)in * (double)gain + canopy_ctx_float(ctx, SETTING_OFFSET));
    return CANOPY_OK;
}

static int32_t scale_span(CanopyCtx *ctx, int32_t outlet, int64_t t0, int64_t t1, int64_t n, float *out)
{
    double offset = canopy_ctx_float(ctx, SETTING_OFFSET);
    float *gain;
    int32_t status;
    int64_t i;
    (void)outlet;
    gain = canopy_scratch(ctx, n);                      /* released by itself when this handler returns; NULL if the arena is exhausted */
    if (!gain) return CANOPY_ERR_MEMORY;
    status = canopy_inlet_span(ctx, INLET_IN, t0, t1, n, out);      /* `out` is ours to write: the signal goes straight into it */
    if (status != CANOPY_OK) return status;
    status = canopy_inlet_span(ctx, INLET_GAIN, t0, t1, n, gain);
    if (status != CANOPY_OK) return status;
    for (i = 0; i < n; i++) out[i] = (float)((double)out[i] * (double)gain[i] + offset);
    return CANOPY_OK;
}

/* ---- the descriptor: all of it is data, and the registry keeps its own copy ---- */

static const CanopyInletDesc inlets[] = {
    { "in", "In", 0.0f },
    { "gain", "Gain", 0.5f },
};
static const CanopyOutletDesc outlets[] = {
    { "out", "Out" },
};
static const CanopySettingDesc settings[] = {
    /* key, kind, default_int, default_float, default_string, n_choices, choices */
    { "offset", CANOPY_SETTING_FLOAT, 0, 0.0, NULL, 0, NULL },
};

CANOPY_API int32_t canopy_example_register(CanopyRegistry *registry)
{
    CanopyNodeType type = { 0 };
    type.abi_version = CANOPY_ABI_VERSION;
    type.struct_size = sizeof(CanopyNodeType);
    type.key = "example.scale";                         /* a key that is not built in must contain a dot: "vendor.name" */
    type.name = "Scale and offset";
    type.type_version = 1;                              /* raise it when the ports or settings change, and register a migration (design section 12) */
    type.flags = CANOPY_FLAG_REALTIME_SAFE;
    type.n_inlets = 2;
    type.inlets = inlets;
    type.n_outlets = 1;
    type.outlets = outlets;
    type.n_settings = 1;
    type.settings = settings;
    type.scratch_buffers = 1;                           /* the most canopy_scratch buffers one call holds at once */
    type.handlers.query_at = scale_at;
    type.handlers.query_span = scale_span;
    return canopy_registry_register(registry, &type);
}
