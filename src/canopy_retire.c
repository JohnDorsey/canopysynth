/* Two things a node needs when other threads are around:
     retiring data   A node that replaces data its queries read (the loaded file, when "open" is pressed again) publishes the new data with an
                     atomic pointer swap and hands the old block to canopy_ctx_retire(). The block is freed once no query that began before the
                     hand-over can still be running. Every host query makes its instance's epoch odd for its duration (see acquire() in
                     canopy_instance.c), so retiring records the instances that were inside a query and waits for each of them to leave it:
                     nothing is locked, allocated or freed in a query. A query that began after the swap reads the new block.
     messages        What a node says about itself ("file not found...") is kept with its record and read by the host. */
#include <stdio.h>
#include <string.h>
#include "canopy_core.h"

typedef struct { CanopyInstance *instance; uint64_t epoch; } CanopyWait;

typedef struct CanopyRetired {
    struct CanopyRetired *next;
    void *block;
    void (*release)(void *block);
    int32_t n_waits;
    CanopyWait *waits;                  /* the instances that were inside a query, and the epoch they were in */
} CanopyRetired;

static void entry_free(CanopyRetired *entry)
{
    entry->release(entry->block);
    canopy_free(entry->waits);
    canopy_free(entry);
}

void canopy_ctx_retire(CanopyCtx *ctx, void *block, void (*release)(void *block))
{
    CanopyEngine *engine;
    CanopyRetired *entry;
    CanopyWait *waits;
    int32_t k, count = 0;
    if (!block || !release) return;
    engine = ctx && ctx->node && ctx->node->record ? ctx->node->record->engine : NULL;
    if (!engine) {                                       /* no engine to ask: nothing can be in a query that reads it */
        release(block);
        return;
    }
    entry = (CanopyRetired *)canopy_alloc(sizeof *entry);
    waits = (CanopyWait *)canopy_alloc((size_t)(engine->n_instances > 0 ? engine->n_instances : 1) * sizeof *waits);
    if (!entry || !waits) {                              /* no memory to note who to wait for: wait for them here, one after the other */
        canopy_free(entry);
        canopy_free(waits);
        for (k = 0; k < engine->n_instances; k++) {
            uint64_t epoch = (uint64_t)atomic_load(&engine->instances[k]->epoch);
            while ((epoch & 1u) && (uint64_t)atomic_load(&engine->instances[k]->epoch) == epoch) SwitchToThread();
        }
        release(block);
        return;
    }
    for (k = 0; k < engine->n_instances; k++) {
        uint64_t epoch = (uint64_t)atomic_load(&engine->instances[k]->epoch);       /* (after the caller's swap: both are sequentially consistent) */
        if (epoch & 1u) {
            waits[count].instance = engine->instances[k];
            waits[count].epoch = epoch;
            count++;
        }
    }
    if (count == 0) {                                    /* no query is running: the old block is already unreachable */
        canopy_free(entry);
        canopy_free(waits);
        release(block);
        return;
    }
    entry->block = block;
    entry->release = release;
    entry->n_waits = count;
    entry->waits = waits;
    canopy_lock_exclusive(&engine->retire_lock);
    entry->next = engine->retired;
    engine->retired = entry;
    canopy_unlock_exclusive(&engine->retire_lock);
}

void canopy_retire_collect(CanopyEngine *engine)
{
    CanopyRetired **link, *ready = NULL;
    canopy_lock_exclusive(&engine->retire_lock);
    for (link = &engine->retired; *link;) {
        CanopyRetired *entry = *link;
        int32_t i, waiting = 0;
        for (i = 0; i < entry->n_waits; i++)
            if ((uint64_t)atomic_load(&entry->waits[i].instance->epoch) == entry->waits[i].epoch) waiting = 1;
        if (waiting) {
            link = &entry->next;
        } else {
            *link = entry->next;
            entry->next = ready;
            ready = entry;
        }
    }
    canopy_unlock_exclusive(&engine->retire_lock);
    while (ready) {
        CanopyRetired *next = ready->next;
        entry_free(ready);
        ready = next;
    }
}

void canopy_retire_forget(CanopyEngine *engine, CanopyInstance *instance)
{
    CanopyRetired *entry;
    canopy_lock_exclusive(&engine->retire_lock);
    for (entry = engine->retired; entry; entry = entry->next) {
        int32_t i;
        for (i = 0; i < entry->n_waits;)
            if (entry->waits[i].instance == instance) entry->waits[i] = entry->waits[--entry->n_waits];
            else i++;
    }
    canopy_unlock_exclusive(&engine->retire_lock);
}

/* ---- messages ---- */

void canopy_ctx_set_message(CanopyCtx *ctx, const char *text)
{
    CanopyNodeRecord *record;
    size_t length;
    if (!ctx || !ctx->node || !ctx->node->record || !text) return;
    record = ctx->node->record;
    length = strlen(text);
    if (length > CANOPY_MESSAGE_BYTES - 1) {                       /* cut at a character boundary: never in the middle of a UTF-8 sequence */
        length = CANOPY_MESSAGE_BYTES - 1;
        while (length > 0 && ((unsigned char)text[length] & 0xC0u) == 0x80u) length--;
    }
    canopy_lock_exclusive(&record->engine->message_lock);
    memcpy(record->message, text, length);
    record->message[length] = '\0';
    canopy_unlock_exclusive(&record->engine->message_lock);
}

int32_t canopy_engine_node_message(CanopyEngine *engine, int64_t node_id, char *buffer, int32_t capacity, int32_t *length)
{
    const CanopyCompiled *graph;
    const CanopyCNode *node;
    int32_t status = CANOPY_OK;
    if (!engine || capacity < 0 || (capacity > 0 && !buffer)) return CANOPY_ERR_ARGUMENT;
    canopy_lock_shared(&engine->lock);
    graph = atomic_load_explicit(&engine->current, memory_order_acquire);
    node = graph ? canopy_compiled_find(graph, node_id, NULL) : NULL;
    if (!node) {
        status = CANOPY_ERR_NODE;
    } else {
        size_t size;
        canopy_lock_exclusive(&engine->message_lock);
        size = strlen(node->record->message);
        if (capacity > 0) {
            size_t copied = size < (size_t)capacity - 1 ? size : (size_t)capacity - 1;
            if (copied) memcpy(buffer, node->record->message, copied);
            buffer[copied] = '\0';
        }
        canopy_unlock_exclusive(&engine->message_lock);
        if (length) *length = (int32_t)size;
    }
    canopy_unlock_shared(&engine->lock);
    return status;
}
