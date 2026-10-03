/* Tests: the node-type descriptor and the registry (docs/canopy_design.md section 12). */
#include <math.h>
#include <string.h>
#include "../../src/canopy_internal.h"
#include "ctest.h"

static float dummy_at(CanopyCtx *ctx, int32_t outlet, int64_t t)
{
    (void)ctx; (void)outlet; (void)t;
    return 0.0f;
}

static const CanopyInletDesc INLETS[] = {{"input", "Input", 0.0f}, {"gain", "Gain", 0.5f}};
static const CanopyOutletDesc OUTLETS[] = {{"out", "Out"}};
static const char *const CHOICES[] = {"low", "mid", "high"};
static const CanopySettingDesc SETTINGS[] = {
    {"count", CANOPY_SETTING_INT, 3, 0.0, NULL, 0, NULL},
    {"ratio", CANOPY_SETTING_FLOAT, 0, 1.5, NULL, 0, NULL},
    {"file", CANOPY_SETTING_PATH, 0, 0.0, "C:/a.wav", 0, NULL},
    {"mode", CANOPY_SETTING_CHOICE, 1, 0.0, NULL, 3, CHOICES},
    {"device", CANOPY_SETTING_STRING, 0, 0.0, "default", 0, NULL},
};
static const CanopyWidgetDesc WIDGETS[] = {
    {CANOPY_WIDGET_BUTTON, "Open", NULL, "open", 0, NULL},
    {CANOPY_WIDGET_TEXT, "Count", "count", NULL, 0, NULL},
    {CANOPY_WIDGET_CHOICE, "Mode", "mode", NULL, 0, NULL},
    {CANOPY_WIDGET_LABEL, "Just a label", NULL, NULL, 0, NULL},
};

/* a fully valid descriptor to start each test from */
static CanopyNodeType make_valid(void)
{
    CanopyNodeType type;
    memset(&type, 0, sizeof type);
    type.abi_version = CANOPY_ABI_VERSION;
    type.struct_size = sizeof type;
    type.key = "vendor.thing";
    type.name = "Thing";
    type.type_version = 1;
    type.flags = CANOPY_FLAG_REALTIME_SAFE;
    type.n_inlets = 2; type.inlets = INLETS;
    type.n_outlets = 1; type.outlets = OUTLETS;
    type.n_settings = 5; type.settings = SETTINGS;
    type.n_widgets = 4; type.widgets = WIDGETS;
    type.scratch_buffers = 2;
    type.handlers.query_at = dummy_at;
    return type;
}

static void test_c_a_valid_type_registers_and_reads_back_all_its_metadata(void)
{
    CanopyRegistry *registry = canopy_registry_new_empty();
    CanopyNodeType type = make_valid();
    const CanopyNodeType *found;
    CHECK(canopy_registry_register(registry, &type) == CANOPY_OK);
    CHECK(canopy_registry_count(registry) == 1);
    found = canopy_registry_find(registry, "vendor.thing");
    CHECK(found != NULL && found == canopy_registry_at(registry, 0));
    if (found) {
        CHECK(strcmp(found->name, "Thing") == 0 && found->type_version == 1 && found->flags == CANOPY_FLAG_REALTIME_SAFE);
        CHECK(found->n_inlets == 2 && strcmp(found->inlets[1].key, "gain") == 0 && found->inlets[1].default_knob == 0.5f);
        CHECK(found->n_outlets == 1 && strcmp(found->outlets[0].label, "Out") == 0);
        CHECK(found->n_settings == 5 && found->settings[3].n_choices == 3 && strcmp(found->settings[3].choices[2], "high") == 0);
        CHECK(found->settings[0].default_int == 3 && found->settings[1].default_float == 1.5);
        CHECK(strcmp(found->settings[2].default_string, "C:/a.wav") == 0);
        CHECK(found->n_widgets == 4 && strcmp(found->widgets[0].action, "open") == 0 && strcmp(found->widgets[1].setting, "count") == 0);
        CHECK(found->scratch_buffers == 2 && found->handlers.query_at == dummy_at && found->handlers.query_span == NULL);
    }
    CHECK(canopy_registry_find(registry, "vendor.other") == NULL);
    CHECK(canopy_registry_at(registry, 1) == NULL && canopy_registry_at(registry, -1) == NULL);
    canopy_registry_free(registry);
}

static void test_c_the_registry_keeps_its_own_copy_of_every_string_and_array(void)
{
    CanopyRegistry *registry = canopy_registry_new_empty();
    char key[] = "vendor.copy";
    char label[] = "Label";
    CanopyInletDesc inlet = {"input", label, 0.25f};
    CanopyNodeType type = make_valid();
    const CanopyNodeType *found;
    type.key = key;
    type.n_inlets = 1; type.inlets = &inlet;
    CHECK(canopy_registry_register(registry, &type) == CANOPY_OK);
    memset(key, 'X', sizeof key - 1);
    memset(label, 'Y', sizeof label - 1);
    inlet.default_knob = -1.0f;
    found = canopy_registry_find(registry, "vendor.copy");
    CHECK(found != NULL);
    if (found) CHECK(strcmp(found->inlets[0].label, "Label") == 0 && found->inlets[0].default_knob == 0.25f);
    canopy_registry_free(registry);
}

static void test_c_types_are_listed_in_registration_order(void)
{
    CanopyRegistry *registry = canopy_registry_new_empty();
    CanopyNodeType a = make_valid(), b = make_valid(), c = make_valid();
    a.key = "v.a"; b.key = "v.b"; c.key = "v.c";
    CHECK(canopy_registry_register(registry, &b) == CANOPY_OK);
    CHECK(canopy_registry_register(registry, &a) == CANOPY_OK);
    CHECK(canopy_registry_register(registry, &c) == CANOPY_OK);
    CHECK(canopy_registry_count(registry) == 3);
    CHECK(strcmp(canopy_registry_at(registry, 0)->key, "v.b") == 0 && strcmp(canopy_registry_at(registry, 1)->key, "v.a") == 0);
    canopy_registry_free(registry);
}

static int32_t register_with_key(const char *key, int builtin)
{
    CanopyRegistry *registry = canopy_registry_new_empty();
    CanopyNodeType type = make_valid();
    int32_t status;
    type.key = key;
    status = builtin ? canopy_registry_register_builtin(registry, &type) : canopy_registry_register(registry, &type);
    canopy_registry_free(registry);
    return status;
}

static void test_c_built_in_keys_are_plain_and_every_other_key_needs_a_dot(void)
{
    CHECK(register_with_key("file_read", 1) == CANOPY_OK);
    CHECK(register_with_key("node2", 1) == CANOPY_OK);
    CHECK(register_with_key("vendor.thing", 1) == CANOPY_ERR_KEY);      /* a built-in must not have a dot */
    CHECK(register_with_key("file_read", 0) == CANOPY_ERR_KEY);         /* a third-party key must have one */
    CHECK(register_with_key("vendor.thing", 0) == CANOPY_OK);
    CHECK(register_with_key("a.b.c", 0) == CANOPY_OK);
    CHECK(register_with_key("my_co.fancy_filter2", 0) == CANOPY_OK);
}

static void test_c_malformed_keys_are_refused(void)
{
    const char *bad[] = {"", ".", "vendor.", ".thing", "a..b", "Vendor.thing", "vendor.Thing", "vendor.thing ", "ven dor.x",
                         "vendor-x.y", "vendor.thé", NULL};
    int i;
    for (i = 0; bad[i]; i++) CHECK(register_with_key(bad[i], 0) == CANOPY_ERR_KEY);
    CHECK(register_with_key(NULL, 0) == CANOPY_ERR_KEY);
    CHECK(register_with_key("Bad", 1) == CANOPY_ERR_KEY);
    CHECK(register_with_key("has space", 1) == CANOPY_ERR_KEY);
    CHECK(register_with_key("", 1) == CANOPY_ERR_KEY);
}

static void test_c_a_key_cannot_be_registered_twice(void)
{
    CanopyRegistry *registry = canopy_registry_new_empty();
    CanopyNodeType type = make_valid();
    CHECK(canopy_registry_register(registry, &type) == CANOPY_OK);
    CHECK(canopy_registry_register(registry, &type) == CANOPY_ERR_DUPLICATE);
    CHECK(canopy_registry_count(registry) == 1);
    CHECK(strstr(canopy_registry_last_error(registry), "vendor.thing") != NULL);
    canopy_registry_free(registry);
}

static void test_c_a_descriptor_of_another_layout_version_or_too_small_is_refused(void)
{
    CanopyRegistry *registry = canopy_registry_new_empty();
    CanopyNodeType type = make_valid();
    type.abi_version = CANOPY_ABI_VERSION + 1;
    CHECK(canopy_registry_register(registry, &type) == CANOPY_ERR_ABI);
    type = make_valid(); type.abi_version = 0;
    CHECK(canopy_registry_register(registry, &type) == CANOPY_ERR_ABI);
    type = make_valid(); type.struct_size = (uint32_t)sizeof type - 1;
    CHECK(canopy_registry_register(registry, &type) == CANOPY_ERR_ABI);
    type = make_valid(); type.struct_size = 8;
    CHECK(canopy_registry_register(registry, &type) == CANOPY_ERR_ABI);
    type = make_valid(); type.struct_size = (uint32_t)sizeof type + 64;     /* a newer, larger layout of the same version is fine */
    CHECK(canopy_registry_register(registry, &type) == CANOPY_OK);
    CHECK(canopy_registry_register(registry, NULL) == CANOPY_ERR_DESCRIPTOR);
    canopy_registry_free(registry);
}

static int32_t status_for(CanopyNodeType type)
{
    CanopyRegistry *registry = canopy_registry_new_empty();
    int32_t status = canopy_registry_register(registry, &type);
    CHECK(status == CANOPY_OK || canopy_registry_count(registry) == 0);        /* nothing added on failure */
    CHECK(status == CANOPY_OK || strlen(canopy_registry_last_error(registry)) > 0);
    canopy_registry_free(registry);
    return status;
}

static void test_c_descriptor_faults_are_refused_with_a_message(void)
{
    CanopyNodeType type;
    CanopyInletDesc same_inlets[] = {{"a", "A", 0.0f}, {"a", "B", 0.0f}};
    CanopyInletDesc loud[] = {{"a", "A", 1.5f}};
    CanopyInletDesc nan_knob[] = {{"a", "A", NAN}};
    CanopyInletDesc bad_inlet_key[] = {{"Bad-Key", "A", 0.0f}};
    CanopyOutletDesc same_outlets[] = {{"o", "A"}, {"o", "B"}};
    CanopySettingDesc same_settings[] = {{"s", CANOPY_SETTING_INT, 0, 0, NULL, 0, NULL}, {"s", CANOPY_SETTING_INT, 0, 0, NULL, 0, NULL}};
    CanopySettingDesc bad_kind[] = {{"s", 99, 0, 0, NULL, 0, NULL}};
    CanopySettingDesc no_choices[] = {{"s", CANOPY_SETTING_CHOICE, 0, 0, NULL, 0, NULL}};
    CanopySettingDesc bad_default[] = {{"s", CANOPY_SETTING_CHOICE, 3, 0, NULL, 3, CHOICES}};
    CanopySettingDesc reserved[] = {{CANOPY_INTERNAL_RATE_KEY, CANOPY_SETTING_INT, 0, 0, NULL, 0, NULL}};
    CanopyWidgetDesc bad_widget_kind[] = {{99, "x", NULL, NULL, 0, NULL}};
    CanopyWidgetDesc button_no_action[] = {{CANOPY_WIDGET_BUTTON, "x", NULL, NULL, 0, NULL}};
    CanopyWidgetDesc text_no_setting[] = {{CANOPY_WIDGET_TEXT, "x", "nope", NULL, 0, NULL}};
    CanopyWidgetDesc text_null_setting[] = {{CANOPY_WIDGET_TEXT, "x", NULL, NULL, 0, NULL}};
    CanopyWidgetDesc choice_on_int[] = {{CANOPY_WIDGET_CHOICE, "x", "count", NULL, 2, CHOICES}};
    CanopyWidgetDesc choice_on_string_without_choices[] = {{CANOPY_WIDGET_CHOICE, "x", "device", NULL, 0, NULL}};
    CanopyWidgetDesc choice_differs[] = {{CANOPY_WIDGET_CHOICE, "x", "mode", NULL, 2, CHOICES}};
    CanopyWidgetDesc choice_same[] = {{CANOPY_WIDGET_CHOICE, "x", "mode", NULL, 3, CHOICES}};
    CanopyWidgetDesc choice_on_string[] = {{CANOPY_WIDGET_CHOICE, "x", "device", NULL, 3, CHOICES}};

    type = make_valid(); type.name = NULL;                                      CHECK(status_for(type) == CANOPY_ERR_DESCRIPTOR);
    type = make_valid(); type.name = "";                                        CHECK(status_for(type) == CANOPY_ERR_DESCRIPTOR);
    type = make_valid(); type.type_version = 0;                                 CHECK(status_for(type) == CANOPY_ERR_DESCRIPTOR);
    type = make_valid(); type.flags = 8;                                        CHECK(status_for(type) == CANOPY_ERR_DESCRIPTOR);
    type = make_valid(); type.scratch_buffers = -1;                             CHECK(status_for(type) == CANOPY_ERR_DESCRIPTOR);
    type = make_valid(); type.n_inlets = -1;                                    CHECK(status_for(type) == CANOPY_ERR_DESCRIPTOR);
    type = make_valid(); type.inlets = NULL;                                    CHECK(status_for(type) == CANOPY_ERR_DESCRIPTOR);
    type = make_valid(); type.n_inlets = 2; type.inlets = same_inlets;          CHECK(status_for(type) == CANOPY_ERR_DESCRIPTOR);
    type = make_valid(); type.n_inlets = 1; type.inlets = loud;                 CHECK(status_for(type) == CANOPY_ERR_DESCRIPTOR);
    type = make_valid(); type.n_inlets = 1; type.inlets = nan_knob;             CHECK(status_for(type) == CANOPY_ERR_DESCRIPTOR);
    type = make_valid(); type.n_inlets = 1; type.inlets = bad_inlet_key;        CHECK(status_for(type) == CANOPY_ERR_DESCRIPTOR);
    type = make_valid(); type.n_outlets = 2; type.outlets = same_outlets;       CHECK(status_for(type) == CANOPY_ERR_DESCRIPTOR);
    type = make_valid(); type.n_widgets = 0; type.widgets = NULL; type.n_settings = 2; type.settings = same_settings;    CHECK(status_for(type) == CANOPY_ERR_DESCRIPTOR);
    type = make_valid(); type.n_widgets = 0; type.widgets = NULL; type.n_settings = 1; type.settings = bad_kind;         CHECK(status_for(type) == CANOPY_ERR_DESCRIPTOR);
    type = make_valid(); type.n_widgets = 0; type.widgets = NULL; type.n_settings = 1; type.settings = no_choices;       CHECK(status_for(type) == CANOPY_ERR_DESCRIPTOR);
    type = make_valid(); type.n_widgets = 0; type.widgets = NULL; type.n_settings = 1; type.settings = bad_default;      CHECK(status_for(type) == CANOPY_ERR_DESCRIPTOR);
    type = make_valid(); type.n_widgets = 0; type.widgets = NULL; type.n_settings = 1; type.settings = reserved;         CHECK(status_for(type) == CANOPY_ERR_DESCRIPTOR);
    type = make_valid(); type.n_widgets = 1; type.widgets = bad_widget_kind;    CHECK(status_for(type) == CANOPY_ERR_DESCRIPTOR);
    type = make_valid(); type.n_widgets = 1; type.widgets = button_no_action;   CHECK(status_for(type) == CANOPY_ERR_DESCRIPTOR);
    type = make_valid(); type.n_widgets = 1; type.widgets = text_no_setting;    CHECK(status_for(type) == CANOPY_ERR_DESCRIPTOR);
    type = make_valid(); type.n_widgets = 1; type.widgets = text_null_setting;  CHECK(status_for(type) == CANOPY_ERR_DESCRIPTOR);
    type = make_valid(); type.n_widgets = 1; type.widgets = choice_on_int;      CHECK(status_for(type) == CANOPY_ERR_DESCRIPTOR);
    type = make_valid(); type.n_widgets = 1; type.widgets = choice_on_string_without_choices;
                                                                                CHECK(status_for(type) == CANOPY_ERR_DESCRIPTOR);
    type = make_valid(); type.n_widgets = 1; type.widgets = choice_differs;     CHECK(status_for(type) == CANOPY_ERR_DESCRIPTOR);
    type = make_valid(); type.handlers.query_at = NULL;                         CHECK(status_for(type) == CANOPY_ERR_DESCRIPTOR);
    /* and the neighbours that are fine */
    type = make_valid(); type.n_widgets = 1; type.widgets = choice_same;        CHECK(status_for(type) == CANOPY_OK);
    type = make_valid(); type.n_widgets = 1; type.widgets = choice_on_string;   CHECK(status_for(type) == CANOPY_OK);
    type = make_valid(); type.n_inlets = 0; type.inlets = NULL;                 CHECK(status_for(type) == CANOPY_OK);
    type = make_valid(); type.n_outlets = 0; type.outlets = NULL; type.handlers.query_at = NULL;
                                                                                CHECK(status_for(type) == CANOPY_OK);   /* a sink needs no query handler */
    type = make_valid(); type.n_settings = 0; type.settings = NULL; type.n_widgets = 0; type.widgets = NULL;
                                                                                CHECK(status_for(type) == CANOPY_OK);
    type = make_valid(); type.handlers.query_at = NULL; type.handlers.query_span = (int32_t (*)(CanopyCtx *, int32_t, int64_t, int64_t, int64_t, float *))dummy_at;
                                                                                CHECK(status_for(type) == CANOPY_OK);   /* span only is fine */
}

static void test_c_only_a_built_in_type_may_have_a_boundary_slot(void)
{
    CanopyRegistry *registry = canopy_registry_new_empty();
    CanopyNodeType type = make_valid();
    type.flags = CANOPY_FLAG_BOUNDARY_SLOT;
    CHECK(canopy_registry_register(registry, &type) == CANOPY_ERR_DESCRIPTOR);          /* a type with a dotted key (a plugin's) may not */
    CHECK(canopy_registry_count(registry) == 0);
    type.key = "boundary_thing";
    CHECK(canopy_registry_register_builtin(registry, &type) == CANOPY_OK);              /* a built-in type may */
    CHECK(canopy_registry_find(registry, "boundary_thing") != NULL && (canopy_registry_find(registry, "boundary_thing")->flags & CANOPY_FLAG_BOUNDARY_SLOT));
    type.key = "other_thing";
    type.flags = CANOPY_FLAG_BOUNDARY_SLOT | 8u;
    CHECK(canopy_registry_register_builtin(registry, &type) == CANOPY_ERR_DESCRIPTOR);  /* but not with a flag that does not exist */
    CHECK(canopy_registry_count(registry) == 1);
    canopy_registry_free(registry);
}

static void test_c_a_boundary_node_type_needs_a_string_setting_called_name_and_only_built_in_types_may_be_one(void)
{
    CanopyRegistry *registry = canopy_registry_new_empty();
    CanopyNodeType type = make_valid();
    CanopySettingDesc named[] = {{"name", CANOPY_SETTING_STRING, 0, 0.0, "", 0, NULL}};
    CanopySettingDesc int_named[] = {{"name", CANOPY_SETTING_INT, 0, 0.0, NULL, 0, NULL}};
    CanopySettingDesc other[] = {{"label", CANOPY_SETTING_STRING, 0, 0.0, "", 0, NULL}};
    type.n_widgets = 0; type.widgets = NULL;
    type.n_settings = 1; type.settings = named;
    type.flags = CANOPY_FLAG_BOUNDARY_NODE;
    CHECK(canopy_registry_register(registry, &type) == CANOPY_ERR_DESCRIPTOR);          /* a plug-in type may not be a boundary node */
    type.key = "named_node";
    CHECK(canopy_registry_register_builtin(registry, &type) == CANOPY_OK);
    type.key = "int_named_node"; type.settings = int_named;
    CHECK(canopy_registry_register_builtin(registry, &type) == CANOPY_ERR_DESCRIPTOR);   /* the name must be text */
    type.key = "other_named_node"; type.settings = other;
    CHECK(canopy_registry_register_builtin(registry, &type) == CANOPY_ERR_DESCRIPTOR);   /* and called name */
    type.key = "unnamed_node"; type.n_settings = 0; type.settings = NULL;
    CHECK(canopy_registry_register_builtin(registry, &type) == CANOPY_ERR_DESCRIPTOR);
    CHECK(canopy_registry_count(registry) == 1);
    canopy_registry_free(registry);
}

static void test_c_a_new_registry_that_runs_out_of_memory_is_complete_or_not_there_and_leaks_nothing(void)
{
    int64_t live = canopy_alloc_live(), fail_at;
    int complete = 0, refused = 0;
    for (fail_at = 0; fail_at < 400 && complete < 2; fail_at++) {
        CanopyRegistry *registry;
        canopy_alloc_fail_after(fail_at);
        registry = canopy_registry_new();
        canopy_alloc_fail_after(-1);
        if (registry) {
            CHECK(canopy_registry_find(registry, "boundary_inlet") != NULL && canopy_registry_find(registry, "boundary_outlet") != NULL);
            complete++;
            canopy_registry_free(registry);
        } else {
            refused++;
        }
        CHECK_INT(canopy_alloc_live(), live);
    }
    CHECK(refused > 20);
    CHECK(complete == 2);
}

static void test_c_the_internal_sampling_rate_setting_is_added_when_the_flag_is_set(void)
{
    CanopyRegistry *registry = canopy_registry_new_empty();
    CanopyNodeType with = make_valid(), without = make_valid();
    const CanopyNodeType *found;
    with.key = "v.with"; with.flags = CANOPY_FLAG_HAS_INTERNAL_RATE;
    without.key = "v.without";
    CHECK(canopy_registry_register(registry, &with) == CANOPY_OK);
    CHECK(canopy_registry_register(registry, &without) == CANOPY_OK);
    found = canopy_registry_find(registry, "v.with");
    CHECK(found != NULL && found->n_settings == 6);
    if (found && found->n_settings == 6) {
        CHECK(strcmp(found->settings[5].key, CANOPY_INTERNAL_RATE_KEY) == 0 && found->settings[5].kind == CANOPY_SETTING_INT);
        CHECK(found->settings[5].default_int == 48000);
        CHECK(strcmp(found->settings[0].key, "count") == 0);       /* the author's settings keep their places */
    }
    found = canopy_registry_find(registry, "v.without");
    CHECK(found != NULL && found->n_settings == 5);
    canopy_registry_free(registry);
}

static void test_c_a_widget_may_edit_the_internal_sampling_rate(void)
{
    CanopyRegistry *registry = canopy_registry_new_empty();
    CanopyNodeType type = make_valid();
    CanopyWidgetDesc rate_widget[] = {{CANOPY_WIDGET_TEXT, "Rate", CANOPY_INTERNAL_RATE_KEY, NULL, 0, NULL}};
    type.flags = CANOPY_FLAG_HAS_INTERNAL_RATE;
    type.n_widgets = 1; type.widgets = rate_widget;
    CHECK(canopy_registry_register(registry, &type) == CANOPY_OK);
    canopy_registry_free(registry);
}

static void test_c_the_descriptor_has_the_size_the_python_mirror_expects(void)
{
    volatile size_t type_size = sizeof(CanopyNodeType), setting_size = sizeof(CanopySettingDesc);
    volatile size_t widget_size = sizeof(CanopyWidgetDesc), handlers_size = sizeof(CanopyHandlers);
    CHECK(type_size == 160);                        /* the same literals are pinned in tests/python/test_registry.py */
    CHECK(setting_size == 56 && widget_size == 48);
    CHECK(handlers_size == 56);
}

static void test_c_status_messages_exist_for_every_code(void)
{
    int32_t code;
    for (code = 0; code <= CANOPY_STATUS_LAST; code++) CHECK(canopy_status_message(code) != NULL && strlen(canopy_status_message(code)) > 3);
    CHECK(strcmp(canopy_status_message(CANOPY_STATUS_LAST + 1), "unknown status code") == 0);   /* CANOPY_STATUS_LAST is really the last */
    CHECK(canopy_status_message(12345) != NULL);
    CHECK(canopy_abi_version() == CANOPY_ABI_VERSION);
}

void register_test_registry(void)
{
    RUN(test_c_a_valid_type_registers_and_reads_back_all_its_metadata);
    RUN(test_c_the_registry_keeps_its_own_copy_of_every_string_and_array);
    RUN(test_c_types_are_listed_in_registration_order);
    RUN(test_c_built_in_keys_are_plain_and_every_other_key_needs_a_dot);
    RUN(test_c_malformed_keys_are_refused);
    RUN(test_c_a_key_cannot_be_registered_twice);
    RUN(test_c_a_descriptor_of_another_layout_version_or_too_small_is_refused);
    RUN(test_c_descriptor_faults_are_refused_with_a_message);
    RUN(test_c_only_a_built_in_type_may_have_a_boundary_slot);
    RUN(test_c_a_boundary_node_type_needs_a_string_setting_called_name_and_only_built_in_types_may_be_one);
    RUN(test_c_a_new_registry_that_runs_out_of_memory_is_complete_or_not_there_and_leaks_nothing);
    RUN(test_c_the_internal_sampling_rate_setting_is_added_when_the_flag_is_set);
    RUN(test_c_a_widget_may_edit_the_internal_sampling_rate);
    RUN(test_c_the_descriptor_has_the_size_the_python_mirror_expects);
    RUN(test_c_status_messages_exist_for_every_code);
}
