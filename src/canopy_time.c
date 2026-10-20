/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "canopy.h"
#include "canopy_internal.h"

#define NS_PER_SEC 1000000000LL

/* Splits ns into whole seconds (floor) and remaining nanoseconds 0..NS_PER_SEC-1 without multiplying (so INT64_MIN is safe). */
static void split_ns(int64_t ns, int64_t *sec, int64_t *rem)
{
    int64_t s = ns / NS_PER_SEC;
    int64_t r = ns % NS_PER_SEC;
    if (r < 0) {
        r += NS_PER_SEC;
        s -= 1;
    }
    *sec = s;
    *rem = r;
}

/* sec * rate + low, every step checked; returns CANOPY_OK or CANOPY_ERR_OVERFLOW. rate >= 1 and 0 <= low <= rate.
   For a negative sec the product alone can be below INT64_MIN while the sum is not (INT64_MIN itself), so the sum is rearranged as
   (sec + 1) * rate + (low - rate): the first term is checked, then the second (which is <= 0) is added with a check. */
static int combine(int64_t sec, int64_t rate, int64_t low, int64_t *out)
{
    int64_t product, adjust;
    if (sec >= 0) {
        if (sec > INT64_MAX / rate) return CANOPY_ERR_OVERFLOW;
        product = sec * rate;
        if (product > INT64_MAX - low) return CANOPY_ERR_OVERFLOW;
        *out = product + low;
        return CANOPY_OK;
    }
    if (sec + 1 < INT64_MIN / rate) return CANOPY_ERR_OVERFLOW;
    product = (sec + 1) * rate;
    adjust = low - rate;
    if (adjust < 0 && product < INT64_MIN - adjust) return CANOPY_ERR_OVERFLOW;
    *out = product + adjust;
    return CANOPY_OK;
}

int canopy_ns_to_frame(int64_t ns, int64_t rate, int64_t *out)
{
    int64_t sec, rem, low, frame;
    int status;
    if (rate < 1 || rate > CANOPY_MAX_HELPER_RATE) return CANOPY_ERR_RATE;
    split_ns(ns, &sec, &rem);
    low = (rem * rate + 500000000LL) / NS_PER_SEC;          /* rem * rate >= 0 and fits: rem < 1e9, rate <= INT64_MAX / 1e9 */
    status = combine(sec, rate, low, &frame);
    if (status != CANOPY_OK) return status;
    *out = frame;
    return CANOPY_OK;
}

int canopy_ns_to_frame_fraction(int64_t ns, int64_t rate, int64_t *frame, double *fraction)
{
    int64_t sec, rem, scaled, low, result;
    int status;
    if (rate < 1 || rate > CANOPY_MAX_HELPER_RATE) return CANOPY_ERR_RATE;
    split_ns(ns, &sec, &rem);
    scaled = rem * rate;                                     /* 0 .. ~9.2e18, fits */
    low = scaled / NS_PER_SEC;
    status = combine(sec, rate, low, &result);
    if (status != CANOPY_OK) return status;
    *frame = result;
    *fraction = (double)(scaled % NS_PER_SEC) / 1e9;          /* numerator < 2^53 and 1e9 are exact, so this is correctly rounded */
    return CANOPY_OK;
}

int32_t canopy_frame_to_ns(int64_t frame, int64_t rate, int64_t *ns)
{
    int64_t sec, rem, low, base;
    if (rate < 1 || rate > CANOPY_INTERNAL_RATE_MAX) return CANOPY_ERR_RATE;
    sec = frame / rate;
    rem = frame % rate;
    if (rem < 0) {                                            /* floor division: 0 <= rem < rate */
        rem += rate;
        sec -= 1;
    }
    low = (2 * rem * NS_PER_SEC + rate) / (2 * rate);          /* round half up; rem < rate <= 384000, so the numerator is below 7.7e14 */
    if (sec > INT64_MAX / NS_PER_SEC || sec < INT64_MIN / NS_PER_SEC) return CANOPY_ERR_OVERFLOW;
    base = sec * NS_PER_SEC;
    if (base > INT64_MAX - low) return CANOPY_ERR_OVERFLOW;
    *ns = base + low;
    return CANOPY_OK;
}

int32_t canopy_span_plan(int64_t t0, int64_t t1, int64_t n, CanopySpanPlan *plan)
{
    int64_t d, q, r;
    if (n < 1 || n > CANOPY_MAX_N) return CANOPY_ERR_N;
    if (canopy_span_overflows(t0, t1)) return CANOPY_ERR_OVERFLOW;
    d = t1 - t0;
    q = d / n;
    r = d % n;
    if (r < 0) {                                              /* floor division: the remainder is 0 .. n-1 */
        r += n;
        q -= 1;
    }
    plan->t0 = t0;
    plan->q = q;
    plan->r = r;
    plan->n = n;
    return CANOPY_OK;
}

int64_t canopy_span_plan_time(const CanopySpanPlan *plan, int64_t i)
{
    /* d = q * n + r, so floor(i * d / n) = i * q + floor(i * r / n); it lies between 0 and d, so t0 + offset lies between t0 and t1.
       i * q cannot overflow because n * (n - 1) < 2^63; i * r < n * n. */
    return plan->t0 + (i * plan->q + (i * plan->r) / plan->n);
}

int canopy_sample_time(int64_t t0, int64_t t1, int64_t n, int64_t i, int64_t *out)
{
    CanopySpanPlan plan;
    int32_t status;
    if (n < 1 || n > CANOPY_MAX_N) return CANOPY_ERR_N;
    if (i < 0 || i >= n) return CANOPY_ERR_INDEX;
    status = canopy_span_plan(t0, t1, n, &plan);
    if (status != CANOPY_OK) return status;
    *out = canopy_span_plan_time(&plan, i);
    return CANOPY_OK;
}
