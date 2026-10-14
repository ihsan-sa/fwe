#include "fwe_stub.h"

int32_t fwe_stub_clamp_mb(int32_t gain_mb, int32_t lo, int32_t hi)
{
    if (lo > hi) {
        int32_t t = lo;
        lo = hi;
        hi = t;
    }
    if (gain_mb < lo) {
        return lo;
    }
    return gain_mb > hi ? hi : gain_mb;
}
