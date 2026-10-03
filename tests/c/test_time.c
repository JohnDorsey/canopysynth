/* Tests: the time helpers (docs/canopy_design.md section 4, and the sample placement of section 5). Hand-checked vectors; the heavy
   cross-checking against Python big integers is in tests/python/test_time.py. */
#include <stdint.h>
#include "../../src/canopy.h"
#include "../../src/canopy_internal.h"
#include "ctest.h"

static int64_t frame_of(int64_t ns, int64_t rate)
{
    int64_t out = 12345;
    int status = canopy_ns_to_frame(ns, rate, &out);
    return status == CANOPY_OK ? out : INT64_MIN;
}

static void test_c_ns_to_frame_rounds_half_up_with_floor_division(void)
{
    CHECK(frame_of(0, 48000) == 0);
    CHECK(frame_of(10416, 48000) == 0);
    CHECK(frame_of(10417, 48000) == 1);
    CHECK(frame_of(-10416, 48000) == 0);
    CHECK(frame_of(-10417, 48000) == -1);
    CHECK(frame_of(500000000, 1) == 1);        /* a tie goes up... */
    CHECK(frame_of(-500000000, 1) == 0);       /* ...also for negative times */
    CHECK(frame_of(1500000000, 1) == 2);
    CHECK(frame_of(-1500000000, 1) == -1);
    CHECK(frame_of(1000000000, 44100) == 44100);
}

static void test_c_ns_to_frame_handles_the_int64_limits_without_overflow(void)
{
    CHECK(frame_of(INT64_MAX, 1) == 9223372037LL);
    CHECK(frame_of(INT64_MIN, 1) == -9223372037LL);   /* -9223372036.85 + 0.5, floored */
    CHECK(frame_of(INT64_MAX, 48000) == 442721857769029LL);
    /* regression: the product sec * rate alone is below INT64_MIN here, but the true frame is exactly INT64_MIN */
    CHECK(frame_of(INT64_MIN, 1000000000LL) == INT64_MIN);
}

static void test_c_ns_to_frame_reports_a_bad_rate_and_an_overflowing_result(void)
{
    int64_t out = 7;
    CHECK(canopy_ns_to_frame(1, 0, &out) == CANOPY_ERR_RATE);
    CHECK(canopy_ns_to_frame(1, -48000, &out) == CANOPY_ERR_RATE);
    CHECK(canopy_ns_to_frame(1, 9223372037LL, &out) == CANOPY_ERR_RATE);
    CHECK(canopy_ns_to_frame(INT64_MAX, 9223372036LL, &out) == CANOPY_ERR_OVERFLOW);
    CHECK(canopy_ns_to_frame(INT64_MIN, 9223372036LL, &out) == CANOPY_ERR_OVERFLOW);
}

static void test_c_blocks_tile_exactly_when_their_lengths_are_frame_differences(void)
{
    /* two blocks of 15000 ns at 48000 Hz: rounding each duration would give 1 + 1 = 2 frames, the tiling rule gives 1 + 0 = 1 = the whole */
    CHECK(frame_of(15000, 48000) - frame_of(0, 48000) == 1);
    CHECK(frame_of(30000, 48000) - frame_of(15000, 48000) == 0);
    CHECK(frame_of(30000, 48000) - frame_of(0, 48000) == 1);
}

static void test_c_ns_to_frame_fraction_gives_the_floor_frame_and_a_fraction_in_zero_to_one(void)
{
    int64_t frame = 0;
    double fraction = -1.0;
    CHECK(canopy_ns_to_frame_fraction(2500000000LL, 1, &frame, &fraction) == CANOPY_OK);
    CHECK(frame == 2 && fraction == 0.5);
    CHECK(canopy_ns_to_frame_fraction(-500000000LL, 1, &frame, &fraction) == CANOPY_OK);
    CHECK(frame == -1 && fraction == 0.5);
    CHECK(canopy_ns_to_frame_fraction(0, 48000, &frame, &fraction) == CANOPY_OK);
    CHECK(frame == 0 && fraction == 0.0);
    CHECK(canopy_ns_to_frame_fraction(1, 0, &frame, &fraction) == CANOPY_ERR_RATE);
    CHECK(canopy_ns_to_frame_fraction(INT64_MAX, 9223372036LL, &frame, &fraction) == CANOPY_ERR_OVERFLOW);
}

static int64_t time_of(int64_t t0, int64_t t1, int64_t n, int64_t i)
{
    int64_t out = 12345;
    int status = canopy_sample_time(t0, t1, n, i, &out);
    return status == CANOPY_OK ? out : INT64_MIN;
}

static void test_c_sample_time_places_samples_evenly_with_the_last_before_t1(void)
{
    CHECK(time_of(0, 100, 4, 0) == 0 && time_of(0, 100, 4, 1) == 25 && time_of(0, 100, 4, 2) == 50 && time_of(0, 100, 4, 3) == 75);
    CHECK(time_of(0, 10, 3, 0) == 0 && time_of(0, 10, 3, 1) == 3 && time_of(0, 10, 3, 2) == 6);
    CHECK(time_of(-5, 0, 2, 1) == -3);
}

static void test_c_sample_time_plays_a_reversed_span_and_an_empty_span(void)
{
    CHECK(time_of(100, 0, 4, 0) == 100 && time_of(100, 0, 4, 1) == 75 && time_of(100, 0, 4, 3) == 25);
    CHECK(time_of(0, -5, 2, 1) == -3);          /* floor, not truncation */
    CHECK(time_of(42, 42, 5, 0) == 42 && time_of(42, 42, 5, 4) == 42);
}

static void test_c_sample_time_reports_bad_arguments(void)
{
    int64_t out = 7;
    CHECK(canopy_sample_time(0, 10, 0, 0, &out) == CANOPY_ERR_N);
    CHECK(canopy_sample_time(0, 10, -1, 0, &out) == CANOPY_ERR_N);
    CHECK(canopy_sample_time(0, 10, CANOPY_MAX_N + 1, 0, &out) == CANOPY_ERR_N);
    CHECK(canopy_sample_time(0, 10, CANOPY_MAX_N, CANOPY_MAX_N - 1, &out) == CANOPY_OK);
    CHECK(canopy_sample_time(0, 10, 4, 4, &out) == CANOPY_ERR_INDEX);
    CHECK(canopy_sample_time(0, 10, 4, -1, &out) == CANOPY_ERR_INDEX);
    CHECK(canopy_sample_time(-2, INT64_MAX, 4, 0, &out) == CANOPY_ERR_OVERFLOW);   /* t1 - t0 overflows */
    CHECK(canopy_sample_time(2, INT64_MIN, 4, 0, &out) == CANOPY_ERR_OVERFLOW);
}

static void test_c_sample_time_stays_inside_the_span_even_at_the_int64_limits(void)
{
    int64_t i, t;
    for (i = 0; i < 4; i++) {
        t = time_of(0, INT64_MAX, 4, i);
        CHECK(t >= 0 && t <= INT64_MAX);
        t = time_of(-1, INT64_MAX - 1, 4, i);
        CHECK(t >= -1 && t <= INT64_MAX - 1);
        t = time_of(INT64_MAX, 0, 4, i);
        CHECK(t >= 0 && t <= INT64_MAX);
    }
    CHECK(time_of(0, INT64_MAX, 2, 1) == INT64_MAX / 2);
}

/* canopy_frame_to_ns (internal, used by the grid of the hidden filter): the time in ns of frame `frame` of a grid of `rate` Hz anchored at 0,
   the exact value rounded half up. INT64_MIN stands for "not OK" below. */
static int64_t ns_of(int64_t frame, int64_t rate)
{
    int64_t out = 12345;
    int32_t status = canopy_frame_to_ns(frame, rate, &out);
    return status == CANOPY_OK ? out : INT64_MIN;
}

static void test_c_frame_to_ns_gives_the_exact_time_rounded_half_up_for_positive_and_negative_frames(void)
{
    CHECK(ns_of(0, 48000) == 0 && ns_of(0, 1) == 0);
    CHECK(ns_of(1, 1) == 1000000000LL && ns_of(5, 1) == 5000000000LL && ns_of(-1, 1) == -1000000000LL);
    CHECK(ns_of(1, 2) == 500000000 && ns_of(3, 2) == 1500000000LL && ns_of(-1, 2) == -500000000);
    /* 48000 Hz: 1 / 48000 s = 20833.33 ns, 2 / 48000 = 41666.67 ns, 3 / 48000 = 62500 ns */
    CHECK(ns_of(1, 48000) == 20833 && ns_of(2, 48000) == 41667 && ns_of(3, 48000) == 62500);
    CHECK(ns_of(-1, 48000) == -20833 && ns_of(-2, 48000) == -41667 && ns_of(-3, 48000) == -62500);
    CHECK(ns_of(48000, 48000) == 1000000000LL && ns_of(48001, 48000) == 1000020833LL && ns_of(48002, 48000) == 1000041667LL);
    CHECK(ns_of(-48001, 48000) == -1000020833LL && ns_of(-48002, 48000) == -1000041667LL);
    /* thirds and sevenths */
    CHECK(ns_of(1, 3) == 333333333 && ns_of(2, 3) == 666666667 && ns_of(-1, 3) == -333333333 && ns_of(-2, 3) == -666666667);
    CHECK(ns_of(1, 7) == 142857143 && ns_of(2, 7) == 285714286 && ns_of(3, 7) == 428571429);
}

static void test_c_frame_to_ns_rounds_a_tie_up_also_for_negative_times(void)
{
    /* 1024 Hz: 1 / 1024 s = 976562.5 ns exactly, and every odd frame is such a tie */
    CHECK(ns_of(1, 1024) == 976563 && ns_of(3, 1024) == 2929688 && ns_of(1023, 1024) == 999023438 && ns_of(1025, 1024) == 1000976563LL);
    CHECK(ns_of(-1, 1024) == -976562 && ns_of(-3, 1024) == -2929687 && ns_of(-1023, 1024) == -999023437 && ns_of(-1025, 1024) == -1000976562LL);
    CHECK(ns_of(2, 1024) == 1953125 && ns_of(-2, 1024) == -1953125);               /* the even ones are whole */
    /* 384000 Hz: 3 / 384000 s = 7812.5 ns */
    CHECK(ns_of(1, 384000) == 2604 && ns_of(3, 384000) == 7813 && ns_of(-3, 384000) == -7812 && ns_of(384000, 384000) == 1000000000LL);
}

static void test_c_frame_to_ns_refuses_a_bad_rate_and_a_time_beyond_the_int64_range(void)
{
    int64_t out = 7;
    CHECK(canopy_frame_to_ns(1, 0, &out) == CANOPY_ERR_RATE);
    CHECK(canopy_frame_to_ns(1, -48000, &out) == CANOPY_ERR_RATE);
    CHECK(canopy_frame_to_ns(1, 384001, &out) == CANOPY_ERR_RATE);
    CHECK(canopy_frame_to_ns(1, 384000, &out) == CANOPY_OK);
    CHECK(out == 2604);
    out = 7;
    CHECK(canopy_frame_to_ns(9223372037LL, 1, &out) == CANOPY_ERR_OVERFLOW);        /* whole seconds beyond the range, above and below */
    CHECK(canopy_frame_to_ns(-9223372037LL, 1, &out) == CANOPY_ERR_OVERFLOW);
    CHECK(canopy_frame_to_ns(INT64_MAX, 1, &out) == CANOPY_ERR_OVERFLOW);
    CHECK(canopy_frame_to_ns(INT64_MIN, 384000, &out) == CANOPY_ERR_OVERFLOW);
    CHECK(out == 7);                                                                 /* nothing is written on a failure */
    CHECK(ns_of(9223372036LL, 1) == 9223372036000000000LL && ns_of(-9223372036LL, 1) == -9223372036000000000LL);   /* the last whole seconds that fit */
    /* the seconds fit but the fraction pushes the sum over INT64_MAX: .8 s fits (...036.8 s), .9 s does not */
    CHECK(ns_of(92233720368LL, 10) == 9223372036800000000LL);
    CHECK(canopy_frame_to_ns(92233720369LL, 10, &out) == CANOPY_ERR_OVERFLOW);
    CHECK(out == 7);
}

void register_test_time(void)
{
    RUN(test_c_ns_to_frame_rounds_half_up_with_floor_division);
    RUN(test_c_ns_to_frame_handles_the_int64_limits_without_overflow);
    RUN(test_c_ns_to_frame_reports_a_bad_rate_and_an_overflowing_result);
    RUN(test_c_blocks_tile_exactly_when_their_lengths_are_frame_differences);
    RUN(test_c_ns_to_frame_fraction_gives_the_floor_frame_and_a_fraction_in_zero_to_one);
    RUN(test_c_sample_time_places_samples_evenly_with_the_last_before_t1);
    RUN(test_c_sample_time_plays_a_reversed_span_and_an_empty_span);
    RUN(test_c_sample_time_reports_bad_arguments);
    RUN(test_c_sample_time_stays_inside_the_span_even_at_the_int64_limits);
    RUN(test_c_frame_to_ns_gives_the_exact_time_rounded_half_up_for_positive_and_negative_frames);
    RUN(test_c_frame_to_ns_rounds_a_tie_up_also_for_negative_times);
    RUN(test_c_frame_to_ns_refuses_a_bad_rate_and_a_time_beyond_the_int64_range);
}
