/* The two boundary node types (design sections 10 and 11): how the host talks to a graph. Built-in, registered by canopy_registry_new().
     boundary_inlet   the host writes a value to it by name (canopy_engine_set_boundary); its outlet `out` gives that value for any query,
                      whatever t or t0/t1. It accepts any float. The value lives in the boundary slot of the node's record, so it survives
                      installing another graph (also when the node is renamed) and starts at 0.0 for a node that is new.
     boundary_outlet  the host reads from the graph through its inlet `in` (canopy_instance_read_at and canopy_instance_read_span); an inlet with
                      nothing connected gives its knob, as everywhere. It has no outlet and no handler: nothing inside the graph asks it anything.
   Both have the text setting `name` (empty at first). A graph in which a boundary name is empty or used twice, by either kind, is refused at
   compile time (canopy_engine.c). */
#include <string.h>
#include "canopy_core.h"

static int32_t inlet_at(CanopyCtx *ctx, int32_t outlet, int64_t t, float *out)
{
    (void)outlet; (void)t;
    *out = canopy_ctx_boundary_value(ctx);
    return CANOPY_OK;
}

static int32_t inlet_span(CanopyCtx *ctx, int32_t outlet, int64_t t0, int64_t t1, int64_t n, float *out)
{
    float value = canopy_ctx_boundary_value(ctx);
    int64_t i;
    (void)outlet; (void)t0; (void)t1;
    for (i = 0; i < n; i++) out[i] = value;
    return CANOPY_OK;
}

static const CanopyOutletDesc INLET_OUTLETS[] = {{"out", "Out"}};
static const CanopyInletDesc OUTLET_INLETS[] = {{"in", "In", 0.0f}};
static const CanopySettingDesc NAME_SETTING[] = {{CANOPY_BOUNDARY_NAME_KEY, CANOPY_SETTING_STRING, 0, 0.0, "", 0, NULL}};
static const CanopyWidgetDesc NAME_WIDGET[] = {{CANOPY_WIDGET_TEXT, "Name", CANOPY_BOUNDARY_NAME_KEY, NULL, 0, NULL}};

int32_t canopy_boundary_register_types(CanopyRegistry *registry)
{
    CanopyNodeType type;
    int32_t status;
    memset(&type, 0, sizeof type);
    type.abi_version = CANOPY_ABI_VERSION;
    type.struct_size = (uint32_t)sizeof type;
    type.key = "boundary_inlet";
    type.name = "Boundary inlet";
    type.type_version = 1;
    type.flags = CANOPY_FLAG_REALTIME_SAFE | CANOPY_FLAG_BOUNDARY_NODE | CANOPY_FLAG_BOUNDARY_SLOT;
    type.n_outlets = 1; type.outlets = INLET_OUTLETS;
    type.n_settings = 1; type.settings = NAME_SETTING;
    type.n_widgets = 1; type.widgets = NAME_WIDGET;
    type.handlers.query_at = inlet_at;
    type.handlers.query_span = inlet_span;
    status = canopy_registry_register_builtin(registry, &type);
    if (status != CANOPY_OK) return status;

    memset(&type, 0, sizeof type);
    type.abi_version = CANOPY_ABI_VERSION;
    type.struct_size = (uint32_t)sizeof type;
    type.key = "boundary_outlet";
    type.name = "Boundary outlet";
    type.type_version = 1;
    type.flags = CANOPY_FLAG_REALTIME_SAFE | CANOPY_FLAG_BOUNDARY_NODE;
    type.n_inlets = 1; type.inlets = OUTLET_INLETS;
    type.n_settings = 1; type.settings = NAME_SETTING;
    type.n_widgets = 1; type.widgets = NAME_WIDGET;
    return canopy_registry_register_builtin(registry, &type);
}
