/* canopysynth - public C declarations shared by the engine, the built-in nodes and the tests. */
#ifndef CANOPY_H
#define CANOPY_H

#include <stdint.h>

#ifdef _WIN32
#define CANOPY_API __declspec(dllexport)
#else
#define CANOPY_API
#endif

/* The delivery counter: bumped by exactly 1 once per finished prompt that changed code. The Python package has the same number
   (canopysynth/version.py); a test checks that the two agree, and the Python code refuses to run against a DLL that disagrees. */
#define CANOPYSYNTH_BUILD 18

CANOPY_API int32_t canopy_build_number(void);

/* ---- status codes ----
   Every C function that can fail returns one of these (0 = success). A span query that fails with a nonzero status has zero-filled
   its `out` buffer (all n floats when n is valid). A node's handler may return a nonzero status of its own; the engine passes it on. */
enum {
    CANOPY_OK = 0,
    CANOPY_ERR_RATE = 1,       /* a sample rate outside 1 .. CANOPY_MAX_HELPER_RATE */
    CANOPY_ERR_OVERFLOW = 2,   /* the exact result (or t1 - t0) does not fit in a signed 64-bit integer */
    CANOPY_ERR_N = 3,          /* a sample count n outside 1 .. CANOPY_MAX_N */
    CANOPY_ERR_INDEX = 4,      /* a sample index outside 0 .. n-1 */
    CANOPY_ERR_ABI = 5,        /* a node-type descriptor of another layout version, or too small */
    CANOPY_ERR_KEY = 6,        /* a node-type key that breaks the key rules */
    CANOPY_ERR_DUPLICATE = 7,  /* a node-type key already registered */
    CANOPY_ERR_DESCRIPTOR = 8, /* any other fault in a descriptor (the registry's last error says which) */
    CANOPY_ERR_MEMORY = 9,     /* out of memory */
    CANOPY_ERR_GRAPH = 10,     /* a graph that cannot be compiled (canopy_engine_last_error() says why) */
    CANOPY_ERR_NODE = 11,      /* no node with that ID in the graph, or no boundary node of that name and kind */
    CANOPY_ERR_PORT = 12,      /* an inlet or outlet index outside the node's ports */
    CANOPY_ERR_ARGUMENT = 13,  /* a NULL pointer, a value outside its range, or a call that is not allowed in this place */
    CANOPY_ERR_BUSY = 14       /* the instance is in use by another call, or the engine still has instances */
};
#define CANOPY_STATUS_LAST CANOPY_ERR_BUSY

/* A fixed English sentence for a status code (never NULL). */
CANOPY_API const char *canopy_status_message(int32_t status);

/* The largest sample count of one span query (docs/canopy_design.md section 8). */
#define CANOPY_MAX_N 65536

/* ---- time: the public helper functions (docs/canopy_design.md section 4) ----
   Times are signed 64-bit nanoseconds since t = 0 and the maths never leaves int64 (no 128-bit integers): a time is split into whole
   seconds and remaining nanoseconds first. The largest rate accepted is INT64_MAX / 1e9 = 9223372036 Hz, the largest for which the
   intermediate products fit. */
#define CANOPY_MAX_HELPER_RATE 9223372036LL

/* Public helper function. The sample frame nearest to time `ns` at `rate` Hz:
   floor((ns * rate + 500000000) / 1000000000), i.e. round half up, with floor division so negative times behave consistently.
   Useful for a host that wants a block of N frames at its own rate for [t0, t1): use ns_to_frame(t1) - ns_to_frame(t0), not
   round(t1 - t0), so consecutive blocks [a, b) and [b, c) tile exactly with no gap or overlap.
   Returns CANOPY_ERR_RATE or CANOPY_ERR_OVERFLOW (then *out is untouched). */
CANOPY_API int canopy_ns_to_frame(int64_t ns, int64_t rate, int64_t *out);

/* Public helper function. Where time `ns` falls among the samples at `rate` Hz: the whole frame at or before it (floor, not rounded)
   and the fraction of the way (0 <= fraction < 1) to the next frame. Useful for a node that interpolates between two samples, for
   example reading a file: sample = (1 - fraction) * data[frame] + fraction * data[frame + 1]. The fraction is exact to double precision.
   Returns CANOPY_ERR_RATE or CANOPY_ERR_OVERFLOW (then the outputs are untouched). */
CANOPY_API int canopy_ns_to_frame_fraction(int64_t ns, int64_t rate, int64_t *frame, double *fraction);

/* The time of sample `i` (0 <= i < n) of a span query [t0, t1) with n samples (docs/canopy_design.md section 5):
   t0 + floor(i * (t1 - t0) / n), computed without overflow from the quotient and remainder of (t1 - t0) by n. The last sample
   is strictly before t1; a reversed span (t1 < t0) runs backwards; t1 == t0 puts every sample at t0.
   Returns CANOPY_ERR_N (n not in 1..CANOPY_MAX_N), CANOPY_ERR_INDEX, or CANOPY_ERR_OVERFLOW (t1 - t0 does not fit). */
CANOPY_API int canopy_sample_time(int64_t t0, int64_t t1, int64_t n, int64_t i, int64_t *out);

#endif
