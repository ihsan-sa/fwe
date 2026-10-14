#ifndef FWE_STUB_H
#define FWE_STUB_H

#include <stdint.h>

/* Clamp a gain in millibels to [lo, hi]. Stands in for real logic: core/ code like this
 * is what tests/host/ runs on the build machine. */
int32_t fwe_stub_clamp_mb(int32_t gain_mb, int32_t lo, int32_t hi);

/* Log the board this firmware was built for (ESP-IDF side). */
void fwe_stub_report(void);

#endif
