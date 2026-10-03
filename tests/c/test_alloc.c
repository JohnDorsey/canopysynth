/* Tests: the counted allocations with their failure hook, the pool, and the span plan (internal pieces the engine is built on). */
#include <string.h>
#include "../../src/canopy_internal.h"
#include "../../src/canopy_engine.h"
#include "ctest.h"

static int all_zero(const unsigned char *bytes, size_t count)
{
    size_t i;
    for (i = 0; i < count; i++)
        if (bytes[i] != 0) return 0;
    return 1;
}

static void test_c_allocations_are_zero_filled_counted_and_freed(void)
{
    int64_t live = canopy_alloc_live(), total = canopy_alloc_total();
    unsigned char *block = (unsigned char *)canopy_alloc(100);
    CHECK(block != NULL);
    if (!block) return;
    CHECK(all_zero(block, 100));
    CHECK_INT(canopy_alloc_live(), live + 1);
    CHECK_INT(canopy_alloc_total(), total + 1);
    memset(block, 7, 100);
    block = (unsigned char *)canopy_realloc(block, 100, 300);
    CHECK(block != NULL);
    if (!block) return;
    CHECK(block[0] == 7 && block[99] == 7);                     /* the old content is kept... */
    CHECK(all_zero(block + 100, 200));                          /* ...and the new tail is zero */
    CHECK_INT(canopy_alloc_live(), live + 1);                   /* growing is not a second block */
    canopy_free(block);
    CHECK_INT(canopy_alloc_live(), live);
    canopy_free(NULL);                                          /* fine */
    CHECK_INT(canopy_alloc_live(), live);
    block = (unsigned char *)canopy_alloc(0);                   /* a zero-size request still gives a block */
    CHECK(block != NULL);
    canopy_free(block);
    block = (unsigned char *)canopy_realloc(NULL, 0, 16);       /* realloc of nothing is an allocation */
    CHECK(block != NULL && all_zero(block, 16));
    canopy_free(block);
    CHECK_INT(canopy_alloc_live(), live);
}

static void test_c_the_allocation_hook_fails_the_nth_allocation_and_every_later_one(void)
{
    int64_t live = canopy_alloc_live();
    char *a, *b, *c;
    canopy_alloc_fail_after(2);
    a = (char *)canopy_alloc(8);
    b = (char *)canopy_alloc(8);
    c = (char *)canopy_alloc(8);
    CHECK(a != NULL && b != NULL && c == NULL);
    CHECK(canopy_alloc(8) == NULL);                             /* it stays failing... */
    if (a) a[0] = 5;
    CHECK(canopy_realloc(a, 8, 64) == NULL);                    /* ...also for realloc, which leaves the block valid */
    CHECK(a != NULL && a[0] == 5);
    canopy_free(a);                                             /* freeing still works while allocations fail */
    canopy_alloc_fail_after(-1);                                /* negative: never fail */
    c = (char *)canopy_alloc(8);
    CHECK(c != NULL);
    canopy_free(b);
    canopy_free(c);
    canopy_alloc_fail_after(0);                                 /* 0: the very next one fails */
    CHECK(canopy_alloc(8) == NULL);
    canopy_alloc_fail_after(-1);
    CHECK_INT(canopy_alloc_live(), live);
}

static void test_c_a_pool_frees_everything_at_once_and_can_be_reused(void)
{
    int64_t live = canopy_alloc_live();
    CanopyPool pool;
    char *text;
    int i;
    memset(&pool, 0, sizeof pool);
    for (i = 0; i < 100; i++) {
        unsigned char *block = (unsigned char *)canopy_pool_alloc(&pool, (size_t)(i + 1));
        CHECK(block != NULL && all_zero(block, (size_t)(i + 1)));
        if (block) memset(block, 9, (size_t)(i + 1));
    }
    text = canopy_pool_strdup(&pool, "hello");
    CHECK(text != NULL && strcmp(text, "hello") == 0);
    CHECK(canopy_alloc_live() > live + 100);
    canopy_pool_free(&pool);
    CHECK_INT(canopy_alloc_live(), live);
    text = canopy_pool_strdup(&pool, "again");                  /* usable again after being freed */
    CHECK(text != NULL && strcmp(text, "again") == 0);
    canopy_pool_free(&pool);
    CHECK_INT(canopy_alloc_live(), live);
    canopy_pool_free(&pool);                                    /* freeing an empty pool is fine */
}

static void test_c_a_pool_leaks_nothing_when_an_allocation_fails_at_any_point(void)
{
    int64_t live = canopy_alloc_live();
    int64_t fail_at;
    for (fail_at = 0; fail_at < 80; fail_at++) {
        CanopyPool pool;
        int i, failed = 0;
        memset(&pool, 0, sizeof pool);
        canopy_alloc_fail_after(fail_at);
        for (i = 0; i < 40; i++)
            if (!canopy_pool_alloc(&pool, 24) || !canopy_pool_strdup(&pool, "text")) failed++;
        canopy_alloc_fail_after(-1);
        if (fail_at < 40) CHECK(failed > 0);                    /* the injected failure was really hit */
        canopy_pool_free(&pool);
        CHECK_INT(canopy_alloc_live(), live);
    }
}

static void test_c_a_span_plan_agrees_with_canopy_sample_time_for_every_sample(void)
{
    int64_t t0, t1, n, i, a, b;
    CanopySpanPlan plan;
    for (t0 = -7; t0 <= 7; t0++)
        for (t1 = -7; t1 <= 7; t1++)
            for (n = 1; n <= 9; n++) {
                CHECK_INT(canopy_span_plan(t0, t1, n, &plan), CANOPY_OK);
                for (i = 0; i < n; i++) {
                    CHECK_INT(canopy_sample_time(t0, t1, n, i, &a), CANOPY_OK);
                    b = canopy_span_plan_time(&plan, i);
                    if (a != b) {
                        ctest_current_failed = 1;
                        printf("    plan differs: t0=%lld t1=%lld n=%lld i=%lld: sample_time %lld, plan %lld\n", (long long)t0, (long long)t1,
                               (long long)n, (long long)i, (long long)a, (long long)b);
                    }
                }
            }
    {
        static const int64_t span_ends[][2] = {{0, INT64_MAX}, {INT64_MAX, 0}, {-1, INT64_MAX - 1}, {0, INT64_MIN}, {INT64_MIN, -1},
                                               {-1, INT64_MIN}, {INT64_MIN, INT64_MAX - 1}, {123456789, -987654321987LL}};
        static const int64_t counts[] = {1, 2, 3, 7, 1000, 65535, 65536};
        size_t e, c;
        for (e = 0; e < sizeof span_ends / sizeof span_ends[0]; e++)
            for (c = 0; c < sizeof counts / sizeof counts[0]; c++) {
                int64_t samples[] = {0, 1, counts[c] / 2, counts[c] - 2, counts[c] - 1};
                size_t s;
                t0 = span_ends[e][0];
                t1 = span_ends[e][1];
                n = counts[c];
                a = canopy_sample_time(t0, t1, n, 0, &b);
                if (a == CANOPY_OK) {
                    CHECK_INT(canopy_span_plan(t0, t1, n, &plan), CANOPY_OK);
                    for (s = 0; s < sizeof samples / sizeof samples[0]; s++) {
                        i = samples[s];
                        if (i < 0 || i >= n) continue;
                        CHECK_INT(canopy_sample_time(t0, t1, n, i, &a), CANOPY_OK);
                        CHECK_INT(canopy_span_plan_time(&plan, i), a);
                    }
                } else {
                    CHECK_INT(canopy_span_plan(t0, t1, n, &plan), a);
                }
            }
    }
}

static void test_c_a_span_plan_reports_n_before_overflow(void)
{
    CanopySpanPlan plan;
    CHECK_INT(canopy_span_plan(0, 10, 0, &plan), CANOPY_ERR_N);
    CHECK_INT(canopy_span_plan(0, 10, -3, &plan), CANOPY_ERR_N);
    CHECK_INT(canopy_span_plan(0, 10, CANOPY_MAX_N + 1, &plan), CANOPY_ERR_N);
    CHECK_INT(canopy_span_plan(0, 10, CANOPY_MAX_N, &plan), CANOPY_OK);
    CHECK_INT(canopy_span_plan(-2, INT64_MAX, 4, &plan), CANOPY_ERR_OVERFLOW);
    CHECK_INT(canopy_span_plan(2, INT64_MIN, 4, &plan), CANOPY_ERR_OVERFLOW);
    CHECK_INT(canopy_span_plan(-2, INT64_MAX, 0, &plan), CANOPY_ERR_N);       /* both wrong: n is reported */
    CHECK_INT(canopy_span_plan(0, INT64_MAX, 4, &plan), CANOPY_OK);           /* the largest forward span fits */
    CHECK_INT(canopy_span_plan(0, INT64_MIN, 4, &plan), CANOPY_OK);           /* and so does t1 - t0 == INT64_MIN */
}

void register_test_alloc(void)
{
    RUN(test_c_allocations_are_zero_filled_counted_and_freed);
    RUN(test_c_the_allocation_hook_fails_the_nth_allocation_and_every_later_one);
    RUN(test_c_a_pool_frees_everything_at_once_and_can_be_reused);
    RUN(test_c_a_pool_leaks_nothing_when_an_allocation_fails_at_any_point);
    RUN(test_c_a_span_plan_agrees_with_canopy_sample_time_for_every_sample);
    RUN(test_c_a_span_plan_reports_n_before_overflow);
}
