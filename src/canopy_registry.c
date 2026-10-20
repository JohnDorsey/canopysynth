/* SPDX-License-Identifier: GPL-3.0-or-later */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "canopy_internal.h"

int32_t canopy_abi_version(void)
{
    return CANOPY_ABI_VERSION;
}

const char *canopy_status_message(int32_t status)
{
    switch (status) {
    case CANOPY_OK: return "success";
    case CANOPY_ERR_RATE: return "the sample rate is outside the accepted range";
    case CANOPY_ERR_OVERFLOW: return "the result does not fit in a signed 64-bit integer";
    case CANOPY_ERR_N: return "the sample count n is outside 1 to 65536";
    case CANOPY_ERR_INDEX: return "the sample index is outside 0 to n-1";
    case CANOPY_ERR_ABI: return "the node-type descriptor is of another layout version or too small";
    case CANOPY_ERR_KEY: return "the node-type key breaks the key rules";
    case CANOPY_ERR_DUPLICATE: return "a node type with that key is already registered";
    case CANOPY_ERR_DESCRIPTOR: return "the node-type descriptor is not valid";
    case CANOPY_ERR_MEMORY: return "out of memory";
    case CANOPY_ERR_GRAPH: return "the graph cannot be compiled";
    case CANOPY_ERR_NODE: return "there is no node with that ID";
    case CANOPY_ERR_PORT: return "the inlet or outlet index is out of range";
    case CANOPY_ERR_ARGUMENT: return "an argument is not valid here";
    case CANOPY_ERR_BUSY: return "the instance or engine is in use";
    default: return "unknown status code";
    }
}

/* ---- a registered type: the deep copy plus every allocation made for it, freed together ---- */

typedef struct {
    CanopyNodeType type;          /* first, so a CanopyNodeType* is also an Entry* */
    CanopyPool pool;
} Entry;

struct CanopyRegistry {
    Entry **entries;
    int count, capacity;
    char error[300];
};

static void *entry_alloc(Entry *entry, size_t size)
{
    return canopy_pool_alloc(&entry->pool, size);
}

static char *entry_strdup(Entry *entry, const char *text)
{
    return canopy_pool_strdup(&entry->pool, text);
}

static void entry_free(Entry *entry)
{
    canopy_pool_free(&entry->pool);
    canopy_free(entry);
}

CanopyRegistry *canopy_registry_new_empty(void)
{
    return (CanopyRegistry *)canopy_alloc(sizeof(CanopyRegistry));
}

CanopyRegistry *canopy_registry_new(void)
{
    CanopyRegistry *registry = canopy_registry_new_empty();
    if (registry && (canopy_boundary_register_types(registry) != CANOPY_OK || canopy_fileread_register_type(registry) != CANOPY_OK ||
                     canopy_preview_register_type(registry) != CANOPY_OK)) {   /* (the other built-in node types are registered here as they are added) */
        canopy_registry_free(registry);
        return NULL;
    }
    return registry;
}

void canopy_registry_free(CanopyRegistry *registry)
{
    int i;
    if (!registry) return;
    for (i = 0; i < registry->count; i++) entry_free(registry->entries[i]);
    canopy_free(registry->entries);
    canopy_free(registry);
}

int32_t canopy_registry_count(const CanopyRegistry *registry)
{
    return registry ? registry->count : 0;
}

const CanopyNodeType *canopy_registry_at(const CanopyRegistry *registry, int32_t index)
{
    if (!registry || index < 0 || index >= registry->count) return NULL;
    return &registry->entries[index]->type;
}

const CanopyNodeType *canopy_registry_find(const CanopyRegistry *registry, const char *key)
{
    int i;
    if (!registry || !key) return NULL;
    for (i = 0; i < registry->count; i++)
        if (strcmp(registry->entries[i]->type.key, key) == 0) return &registry->entries[i]->type;
    return NULL;
}

const char *canopy_registry_last_error(const CanopyRegistry *registry)
{
    return registry ? registry->error : "";
}

/* ---- validation ---- */

static int32_t fail(CanopyRegistry *registry, int32_t status, const char *format, const char *a, const char *b)
{
    snprintf(registry->error, sizeof registry->error, format, a ? a : "(null)", b ? b : "(null)");
    return status;
}

static int is_key_char(unsigned char c)
{
    return (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_';
}

/* A flat key: one or more of [a-z0-9_]. */
static int flat_key(const char *s)
{
    if (!s || !*s) return 0;
    for (; *s; s++) if (!is_key_char((unsigned char)*s)) return 0;
    return 1;
}

/* A dotted key: two or more non-empty flat segments separated by single dots. */
static int dotted_key(const char *s)
{
    int dots = 0, segment_length = 0;
    if (!s || !*s) return 0;
    for (; *s; s++) {
        if (*s == '.') {
            if (segment_length == 0) return 0;
            dots++;
            segment_length = 0;
        } else if (is_key_char((unsigned char)*s)) {
            segment_length++;
        } else {
            return 0;
        }
    }
    return dots >= 1 && segment_length > 0;
}

static int non_empty(const char *s)
{
    return s && *s;
}

/* The kind of the setting `key` of a type (the author's settings, or the internal sampling rate the registry adds), or -1 if there is none.
   *desc is the author's declaration, or NULL for the internal sampling rate. */
static int setting_kind(const CanopyNodeType *type, const char *key, const CanopySettingDesc **desc)
{
    int i;
    *desc = NULL;
    for (i = 0; i < type->n_settings; i++)
        if (strcmp(type->settings[i].key, key) == 0) {
            *desc = &type->settings[i];
            return type->settings[i].kind;
        }
    if ((type->flags & CANOPY_FLAG_HAS_INTERNAL_RATE) && strcmp(key, CANOPY_INTERNAL_RATE_KEY) == 0) return CANOPY_SETTING_INT;
    return -1;
}

static int32_t validate(CanopyRegistry *registry, const CanopyNodeType *type, int builtin)
{
    int i, j;
    if (!type) return fail(registry, CANOPY_ERR_DESCRIPTOR, "no descriptor given%s%s", "", "");
    if (type->abi_version != CANOPY_ABI_VERSION)
        return fail(registry, CANOPY_ERR_ABI, "the descriptor has layout version %s, expected another%s", type->abi_version ? "a different number" : "0", "");
    if (type->struct_size < sizeof(CanopyNodeType)) return fail(registry, CANOPY_ERR_ABI, "struct_size is too small for the descriptor%s%s", "", "");
    if (builtin ? !flat_key(type->key) : !dotted_key(type->key))
        return fail(registry, CANOPY_ERR_KEY, builtin ? "built-in key %s must be lowercase letters, digits and underscores%s"
                                                      : "key %s must be segments of lowercase letters, digits and underscores joined by dots (vendor.name)%s",
                    type->key, "");
    if (canopy_registry_find(registry, type->key)) return fail(registry, CANOPY_ERR_DUPLICATE, "a node type with the key %s is already registered%s", type->key, "");
    if (!non_empty(type->name)) return fail(registry, CANOPY_ERR_DESCRIPTOR, "%s: the display name is empty%s", type->key, "");
    if (type->type_version < 1) return fail(registry, CANOPY_ERR_DESCRIPTOR, "%s: type_version must be at least 1%s", type->key, "");
    if (type->flags & ~(builtin ? (CANOPY_FLAGS_KNOWN | CANOPY_FLAG_BOUNDARY_SLOT | CANOPY_FLAG_BOUNDARY_NODE | CANOPY_FLAG_SERVICE) : CANOPY_FLAGS_KNOWN))
        return fail(registry, CANOPY_ERR_DESCRIPTOR, "%s: unknown flag bits%s", type->key, "");    /* (the boundary and service flags are for built-in types only) */
    if (type->scratch_buffers < 0) return fail(registry, CANOPY_ERR_DESCRIPTOR, "%s: scratch_buffers is negative%s", type->key, "");
    if (type->n_inlets < 0 || type->n_outlets < 0 || type->n_settings < 0 || type->n_widgets < 0)
        return fail(registry, CANOPY_ERR_DESCRIPTOR, "%s: a negative count%s", type->key, "");
    if ((type->n_inlets && !type->inlets) || (type->n_outlets && !type->outlets) || (type->n_settings && !type->settings) ||
        (type->n_widgets && !type->widgets))
        return fail(registry, CANOPY_ERR_DESCRIPTOR, "%s: a count is above zero but its array is NULL%s", type->key, "");
    if (type->flags & CANOPY_FLAG_BOUNDARY_NODE) {                                    /* the compiler finds the name of a boundary node by this setting */
        int has_name = 0;
        for (i = 0; i < type->n_settings; i++)
            if (type->settings[i].key && strcmp(type->settings[i].key, CANOPY_BOUNDARY_NAME_KEY) == 0 && type->settings[i].kind == CANOPY_SETTING_STRING)
                has_name = 1;
        if (!has_name) return fail(registry, CANOPY_ERR_DESCRIPTOR, "%s: a boundary node needs a STRING setting called name%s", type->key, "");
    }

    for (i = 0; i < type->n_inlets; i++) {
        const CanopyInletDesc *inlet = &type->inlets[i];
        if (!flat_key(inlet->key)) return fail(registry, CANOPY_ERR_DESCRIPTOR, "%s: inlet key %s is not a valid key", type->key, inlet->key);
        if (!inlet->label) return fail(registry, CANOPY_ERR_DESCRIPTOR, "%s: inlet %s has no label", type->key, inlet->key);
        if (!(inlet->default_knob >= -1.0f && inlet->default_knob <= 1.0f))
            return fail(registry, CANOPY_ERR_DESCRIPTOR, "%s: inlet %s: the default knob position must be from -1 to 1", type->key, inlet->key);
        for (j = 0; j < i; j++)
            if (strcmp(type->inlets[j].key, inlet->key) == 0) return fail(registry, CANOPY_ERR_DESCRIPTOR, "%s: inlet key %s is used twice", type->key, inlet->key);
    }
    for (i = 0; i < type->n_outlets; i++) {
        const CanopyOutletDesc *outlet = &type->outlets[i];
        if (!flat_key(outlet->key)) return fail(registry, CANOPY_ERR_DESCRIPTOR, "%s: outlet key %s is not a valid key", type->key, outlet->key);
        if (!outlet->label) return fail(registry, CANOPY_ERR_DESCRIPTOR, "%s: outlet %s has no label", type->key, outlet->key);
        for (j = 0; j < i; j++)
            if (strcmp(type->outlets[j].key, outlet->key) == 0) return fail(registry, CANOPY_ERR_DESCRIPTOR, "%s: outlet key %s is used twice", type->key, outlet->key);
    }
    for (i = 0; i < type->n_settings; i++) {
        const CanopySettingDesc *setting = &type->settings[i];
        if (!flat_key(setting->key)) return fail(registry, CANOPY_ERR_DESCRIPTOR, "%s: setting key %s is not a valid key", type->key, setting->key);
        if (strcmp(setting->key, CANOPY_INTERNAL_RATE_KEY) == 0)
            return fail(registry, CANOPY_ERR_DESCRIPTOR, "%s: the key %s is reserved (set CANOPY_FLAG_HAS_INTERNAL_RATE instead)", type->key, setting->key);
        for (j = 0; j < i; j++)
            if (strcmp(type->settings[j].key, setting->key) == 0) return fail(registry, CANOPY_ERR_DESCRIPTOR, "%s: setting key %s is used twice", type->key, setting->key);
        if (setting->kind < CANOPY_SETTING_INT || setting->kind > CANOPY_SETTING_CHOICE)
            return fail(registry, CANOPY_ERR_DESCRIPTOR, "%s: setting %s has an unknown kind", type->key, setting->key);
        if (setting->kind == CANOPY_SETTING_CHOICE) {
            if (setting->n_choices < 1 || !setting->choices)
                return fail(registry, CANOPY_ERR_DESCRIPTOR, "%s: choice setting %s needs at least one choice", type->key, setting->key);
            for (j = 0; j < setting->n_choices; j++)
                if (!setting->choices[j]) return fail(registry, CANOPY_ERR_DESCRIPTOR, "%s: choice setting %s has a NULL choice", type->key, setting->key);
            if (setting->default_int < 0 || setting->default_int >= setting->n_choices)
                return fail(registry, CANOPY_ERR_DESCRIPTOR, "%s: the default of choice setting %s is not one of its choices", type->key, setting->key);
        }
        if (setting->kind == CANOPY_SETTING_FLOAT && !isfinite(setting->default_float))
            return fail(registry, CANOPY_ERR_DESCRIPTOR, "%s: the default of setting %s is not finite", type->key, setting->key);
    }
    for (i = 0; i < type->n_widgets; i++) {
        const CanopyWidgetDesc *widget = &type->widgets[i];
        const CanopySettingDesc *bound = NULL;
        int bound_kind;
        if (!widget->label) return fail(registry, CANOPY_ERR_DESCRIPTOR, "%s: a widget has no label", type->key, "");
        switch (widget->kind) {
        case CANOPY_WIDGET_LABEL:
            break;
        case CANOPY_WIDGET_BUTTON:
            if (!non_empty(widget->action)) return fail(registry, CANOPY_ERR_DESCRIPTOR, "%s: button %s has no action name", type->key, widget->label);
            break;
        case CANOPY_WIDGET_TEXT:
        case CANOPY_WIDGET_CHOICE:
            if (!non_empty(widget->setting)) return fail(registry, CANOPY_ERR_DESCRIPTOR, "%s: widget %s names no setting", type->key, widget->label);
            bound_kind = setting_kind(type, widget->setting, &bound);
            if (bound_kind < 0) return fail(registry, CANOPY_ERR_DESCRIPTOR, "%s: widget edits the setting %s, which does not exist", type->key, widget->setting);
            if (widget->kind == CANOPY_WIDGET_CHOICE) {
                if (bound_kind != CANOPY_SETTING_CHOICE && bound_kind != CANOPY_SETTING_STRING)
                    return fail(registry, CANOPY_ERR_DESCRIPTOR, "%s: a choice widget needs a choice or string setting, not %s", type->key, widget->setting);
                if (widget->n_choices < 0 || (widget->n_choices && !widget->choices))
                    return fail(registry, CANOPY_ERR_DESCRIPTOR, "%s: choice widget %s has an invalid choice list", type->key, widget->label);
                if (bound_kind == CANOPY_SETTING_STRING && widget->n_choices < 1)
                    return fail(registry, CANOPY_ERR_DESCRIPTOR, "%s: choice widget %s lists no choices", type->key, widget->label);
                if (bound_kind == CANOPY_SETTING_CHOICE && widget->n_choices != 0) {
                    if (widget->n_choices != bound->n_choices)
                        return fail(registry, CANOPY_ERR_DESCRIPTOR, "%s: choice widget %s differs from the choices of its setting", type->key, widget->label);
                    for (j = 0; j < widget->n_choices; j++)
                        if (!widget->choices[j] || strcmp(widget->choices[j], bound->choices[j]) != 0)
                            return fail(registry, CANOPY_ERR_DESCRIPTOR, "%s: choice widget %s differs from the choices of its setting", type->key, widget->label);
                }
                for (j = 0; j < widget->n_choices; j++)
                    if (!widget->choices[j]) return fail(registry, CANOPY_ERR_DESCRIPTOR, "%s: choice widget %s has a NULL choice", type->key, widget->label);
            }
            break;
        default:
            return fail(registry, CANOPY_ERR_DESCRIPTOR, "%s: widget %s has an unknown kind", type->key, widget->label);
        }
    }
    if (type->n_outlets > 0 && !type->handlers.query_at && !type->handlers.query_span)
        return fail(registry, CANOPY_ERR_DESCRIPTOR, "%s: a node with outlets needs query_at or query_span%s", type->key, "");
    registry->error[0] = '\0';
    return CANOPY_OK;
}

/* ---- the deep copy ---- */

static int copy_strings(Entry *entry, const char *const *from, int32_t n, const char *const **to)
{
    char **list;
    int32_t i;
    if (n == 0) { *to = NULL; return 1; }
    list = (char **)entry_alloc(entry, (size_t)n * sizeof(char *));
    if (!list) return 0;
    for (i = 0; i < n; i++) {
        list[i] = entry_strdup(entry, from[i]);
        if (!list[i]) return 0;
    }
    *to = (const char *const *)list;
    return 1;
}

static int copy_setting(Entry *entry, const CanopySettingDesc *from, CanopySettingDesc *to)
{
    *to = *from;
    to->key = entry_strdup(entry, from->key);
    to->default_string = from->default_string ? entry_strdup(entry, from->default_string) : NULL;
    to->choices = NULL;
    to->n_choices = 0;
    if (!to->key || (from->default_string && !to->default_string)) return 0;
    if (from->kind == CANOPY_SETTING_CHOICE) {
        to->n_choices = from->n_choices;
        if (!copy_strings(entry, from->choices, from->n_choices, &to->choices)) return 0;
    }
    return 1;
}

static Entry *copy_type(const CanopyNodeType *from)
{
    Entry *entry = (Entry *)canopy_alloc(sizeof(Entry));
    CanopyNodeType *to;
    int32_t i, extra = (from->flags & CANOPY_FLAG_HAS_INTERNAL_RATE) ? 1 : 0;
    CanopyInletDesc *inlets;
    CanopyOutletDesc *outlets;
    CanopySettingDesc *settings;
    CanopyWidgetDesc *widgets;
    if (!entry) return NULL;
    to = &entry->type;
    *to = *from;
    to->struct_size = (uint32_t)sizeof(CanopyNodeType);
    to->key = entry_strdup(entry, from->key);
    to->name = entry_strdup(entry, from->name);
    if (!to->key || !to->name) goto fail;

    inlets = (CanopyInletDesc *)entry_alloc(entry, (size_t)from->n_inlets * sizeof *inlets);
    outlets = (CanopyOutletDesc *)entry_alloc(entry, (size_t)from->n_outlets * sizeof *outlets);
    settings = (CanopySettingDesc *)entry_alloc(entry, (size_t)(from->n_settings + extra) * sizeof *settings);
    widgets = (CanopyWidgetDesc *)entry_alloc(entry, (size_t)from->n_widgets * sizeof *widgets);
    if (!inlets || !outlets || !settings || !widgets) goto fail;
    for (i = 0; i < from->n_inlets; i++) {
        inlets[i] = from->inlets[i];
        inlets[i].key = entry_strdup(entry, from->inlets[i].key);
        inlets[i].label = entry_strdup(entry, from->inlets[i].label);
        if (!inlets[i].key || !inlets[i].label) goto fail;
    }
    for (i = 0; i < from->n_outlets; i++) {
        outlets[i].key = entry_strdup(entry, from->outlets[i].key);
        outlets[i].label = entry_strdup(entry, from->outlets[i].label);
        if (!outlets[i].key || !outlets[i].label) goto fail;
    }
    for (i = 0; i < from->n_settings; i++) if (!copy_setting(entry, &from->settings[i], &settings[i])) goto fail;
    if (extra) {
        CanopySettingDesc rate;
        memset(&rate, 0, sizeof rate);
        rate.key = CANOPY_INTERNAL_RATE_KEY;
        rate.kind = CANOPY_SETTING_INT;
        rate.default_int = CANOPY_INTERNAL_RATE_DEFAULT;
        if (!copy_setting(entry, &rate, &settings[from->n_settings])) goto fail;
    }
    for (i = 0; i < from->n_widgets; i++) {
        widgets[i] = from->widgets[i];
        widgets[i].label = entry_strdup(entry, from->widgets[i].label);
        widgets[i].setting = from->widgets[i].setting ? entry_strdup(entry, from->widgets[i].setting) : NULL;
        widgets[i].action = from->widgets[i].action ? entry_strdup(entry, from->widgets[i].action) : NULL;
        widgets[i].choices = NULL;
        if (!widgets[i].label || (from->widgets[i].setting && !widgets[i].setting) || (from->widgets[i].action && !widgets[i].action)) goto fail;
        if (!copy_strings(entry, from->widgets[i].choices, from->widgets[i].n_choices, &widgets[i].choices)) goto fail;
    }
    to->inlets = from->n_inlets ? inlets : NULL;
    to->outlets = from->n_outlets ? outlets : NULL;
    to->settings = (from->n_settings + extra) ? settings : NULL;
    to->n_settings = from->n_settings + extra;
    to->widgets = from->n_widgets ? widgets : NULL;
    return entry;
fail:
    entry_free(entry);
    return NULL;
}

static int32_t register_type(CanopyRegistry *registry, const CanopyNodeType *type, int builtin)
{
    Entry *entry;
    int32_t status;
    if (!registry) return CANOPY_ERR_DESCRIPTOR;
    status = validate(registry, type, builtin);
    if (status != CANOPY_OK) return status;
    entry = copy_type(type);
    if (!entry) return fail(registry, CANOPY_ERR_MEMORY, "out of memory registering %s%s", type->key, "");
    if (registry->count == registry->capacity) {
        int capacity = registry->capacity ? registry->capacity * 2 : 16;
        Entry **grown = (Entry **)canopy_realloc(registry->entries, (size_t)registry->capacity * sizeof(Entry *), (size_t)capacity * sizeof(Entry *));
        if (!grown) {
            entry_free(entry);
            return fail(registry, CANOPY_ERR_MEMORY, "out of memory registering %s%s", type->key, "");
        }
        registry->entries = grown;
        registry->capacity = capacity;
    }
    registry->entries[registry->count++] = entry;
    return CANOPY_OK;
}

int32_t canopy_registry_register(CanopyRegistry *registry, const CanopyNodeType *type)
{
    return register_type(registry, type, 0);
}

int32_t canopy_registry_register_builtin(CanopyRegistry *registry, const CanopyNodeType *type)
{
    return register_type(registry, type, 1);
}
