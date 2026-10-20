/* SPDX-License-Identifier: GPL-3.0-or-later */
/* The graph description (canopy_engine.h): plain recorded data, checked only when it is compiled (canopy_engine.c). */
#include <string.h>
#include "canopy_core.h"

CanopyGraph *canopy_graph_new(void)
{
    return (CanopyGraph *)canopy_alloc(sizeof(CanopyGraph));
}

void canopy_graph_free(CanopyGraph *graph)
{
    if (!graph) return;
    canopy_pool_free(&graph->pool);
    canopy_free(graph->nodes);
    canopy_free(graph->settings);
    canopy_free(graph->knobs);
    canopy_free(graph->connections);
    canopy_free(graph);
}

/* Room for one more element of an array that holds `count` of `*capacity`: the (possibly moved) array, or NULL if memory ran out (then the
   old array is still valid). */
static void *with_room(void *array, int32_t count, int32_t *capacity, size_t element_size)
{
    int32_t wanted;
    void *grown;
    if (count < *capacity) return array;
    wanted = *capacity ? *capacity * 2 : 16;
    grown = canopy_realloc(array, (size_t)*capacity * element_size, (size_t)wanted * element_size);
    if (grown) *capacity = wanted;
    return grown;
}

int32_t canopy_graph_add_node(CanopyGraph *graph, int64_t node_id, const char *type_key)
{
    CanopyGraphNode *nodes;
    char *key;
    if (!graph || !type_key) return CANOPY_ERR_ARGUMENT;
    nodes = (CanopyGraphNode *)with_room(graph->nodes, graph->n_nodes, &graph->cap_nodes, sizeof *nodes);
    if (!nodes) return CANOPY_ERR_MEMORY;
    graph->nodes = nodes;
    key = canopy_pool_strdup(&graph->pool, type_key);
    if (!key) return CANOPY_ERR_MEMORY;
    nodes[graph->n_nodes].id = node_id;
    nodes[graph->n_nodes].type_key = key;
    graph->n_nodes++;
    return CANOPY_OK;
}

static int32_t add_setting(CanopyGraph *graph, int64_t node_id, const char *setting_key, CanopyValueKind kind, int64_t i, double f,
                           const char *s)
{
    CanopyGraphSetting *settings;
    CanopyGraphSetting *record;
    char *key, *text = NULL;
    if (!graph || !setting_key || (kind == CANOPY_VALUE_STRING && !s)) return CANOPY_ERR_ARGUMENT;
    settings = (CanopyGraphSetting *)with_room(graph->settings, graph->n_settings, &graph->cap_settings, sizeof *settings);
    if (!settings) return CANOPY_ERR_MEMORY;
    graph->settings = settings;
    key = canopy_pool_strdup(&graph->pool, setting_key);
    if (!key) return CANOPY_ERR_MEMORY;
    if (s) {
        text = canopy_pool_strdup(&graph->pool, s);
        if (!text) return CANOPY_ERR_MEMORY;
    }
    record = &settings[graph->n_settings++];
    record->node = node_id;
    record->key = key;
    record->kind = kind;
    record->i = i;
    record->f = f;
    record->s = text;
    return CANOPY_OK;
}

int32_t canopy_graph_set_int(CanopyGraph *graph, int64_t node_id, const char *setting_key, int64_t value)
{
    return add_setting(graph, node_id, setting_key, CANOPY_VALUE_INT, value, 0.0, NULL);
}

int32_t canopy_graph_set_float(CanopyGraph *graph, int64_t node_id, const char *setting_key, double value)
{
    return add_setting(graph, node_id, setting_key, CANOPY_VALUE_FLOAT, 0, value, NULL);
}

int32_t canopy_graph_set_string(CanopyGraph *graph, int64_t node_id, const char *setting_key, const char *value)
{
    return add_setting(graph, node_id, setting_key, CANOPY_VALUE_STRING, 0, 0.0, value);
}

int32_t canopy_graph_set_knob(CanopyGraph *graph, int64_t node_id, const char *inlet_key, float value)
{
    CanopyGraphKnob *knobs;
    char *key;
    if (!graph || !inlet_key) return CANOPY_ERR_ARGUMENT;
    knobs = (CanopyGraphKnob *)with_room(graph->knobs, graph->n_knobs, &graph->cap_knobs, sizeof *knobs);
    if (!knobs) return CANOPY_ERR_MEMORY;
    graph->knobs = knobs;
    key = canopy_pool_strdup(&graph->pool, inlet_key);
    if (!key) return CANOPY_ERR_MEMORY;
    knobs[graph->n_knobs].node = node_id;
    knobs[graph->n_knobs].key = key;
    knobs[graph->n_knobs].value = value;
    graph->n_knobs++;
    return CANOPY_OK;
}

int32_t canopy_graph_connect(CanopyGraph *graph, int64_t from_node, const char *outlet_key, int64_t to_node, const char *inlet_key)
{
    CanopyGraphConnection *connections;
    char *outlet, *inlet;
    if (!graph || !outlet_key || !inlet_key) return CANOPY_ERR_ARGUMENT;
    connections = (CanopyGraphConnection *)with_room(graph->connections, graph->n_connections, &graph->cap_connections, sizeof *connections);
    if (!connections) return CANOPY_ERR_MEMORY;
    graph->connections = connections;
    outlet = canopy_pool_strdup(&graph->pool, outlet_key);
    inlet = outlet ? canopy_pool_strdup(&graph->pool, inlet_key) : NULL;
    if (!outlet || !inlet) return CANOPY_ERR_MEMORY;
    connections[graph->n_connections].from_node = from_node;
    connections[graph->n_connections].outlet_key = outlet;
    connections[graph->n_connections].to_node = to_node;
    connections[graph->n_connections].inlet_key = inlet;
    graph->n_connections++;
    return CANOPY_OK;
}
