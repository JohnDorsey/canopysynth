/* Counted allocations with a failure hook for tests, and the pool (declared in canopy_internal.h; the two counters are exported). */
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
#include "canopy_core.h"

static atomic_llong live_blocks;                 /* blocks allocated and not yet freed */
static atomic_llong total_allocations;           /* allocations and growths that succeeded */
static atomic_llong fail_countdown = -1;         /* >0: that many more succeed; 0: all fail; <0: never fail */

/* 1 if this allocation is to fail; counts down while the allowed successes last. */
static int should_fail(void)
{
    long long left = atomic_load(&fail_countdown);
    for (;;) {
        if (left < 0) return 0;
        if (left == 0) return 1;
        if (atomic_compare_exchange_weak(&fail_countdown, &left, left - 1)) return 0;
    }
}

void canopy_alloc_fail_after(int64_t n)
{
    atomic_store(&fail_countdown, (long long)n);
}

void *canopy_alloc(size_t size)
{
    void *block;
    if (should_fail()) return NULL;
    block = calloc(1, size ? size : 1);
    if (block) {
        atomic_fetch_add(&live_blocks, 1);
        atomic_fetch_add(&total_allocations, 1);
    }
    return block;
}

void *canopy_realloc(void *block, size_t old_size, size_t new_size)
{
    void *grown;
    if (!block) return canopy_alloc(new_size);
    if (should_fail()) return NULL;
    grown = realloc(block, new_size ? new_size : 1);
    if (!grown) return NULL;
    if (new_size > old_size) memset((char *)grown + old_size, 0, new_size - old_size);
    atomic_fetch_add(&total_allocations, 1);
    return grown;
}

void canopy_free(void *block)
{
    if (!block) return;
    free(block);
    atomic_fetch_sub(&live_blocks, 1);
}

int64_t canopy_alloc_live(void)
{
    return (int64_t)atomic_load(&live_blocks);
}

int64_t canopy_alloc_total(void)
{
    return (int64_t)atomic_load(&total_allocations);
}

/* ---- the pool ---- */

void *canopy_pool_alloc(CanopyPool *pool, size_t size)
{
    void *block;
    if (pool->count == pool->capacity) {
        int32_t capacity = pool->capacity ? pool->capacity * 2 : 32;
        void **grown = (void **)canopy_realloc(pool->blocks, (size_t)pool->capacity * sizeof(void *), (size_t)capacity * sizeof(void *));
        if (!grown) return NULL;
        pool->blocks = grown;
        pool->capacity = capacity;
    }
    block = canopy_alloc(size);
    if (!block) return NULL;
    pool->blocks[pool->count++] = block;
    return block;
}

char *canopy_pool_strdup(CanopyPool *pool, const char *text)
{
    size_t length = strlen(text) + 1;
    char *copy = (char *)canopy_pool_alloc(pool, length);
    if (copy) memcpy(copy, text, length);
    return copy;
}

void canopy_pool_free(CanopyPool *pool)
{
    int32_t i;
    for (i = 0; i < pool->count; i++) canopy_free(pool->blocks[i]);
    canopy_free(pool->blocks);
    pool->blocks = NULL;
    pool->count = 0;
    pool->capacity = 0;
}
