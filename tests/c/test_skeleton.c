#include "../../src/canopy.h"
#include "ctest.h"

static void test_c_the_build_number_function_returns_the_header_constant(void)
{
    CHECK(canopy_build_number() == CANOPYSYNTH_BUILD);
    CHECK(canopy_build_number() >= 1);
}

void register_test_skeleton(void)
{
    RUN(test_c_the_build_number_function_returns_the_header_constant);
}
