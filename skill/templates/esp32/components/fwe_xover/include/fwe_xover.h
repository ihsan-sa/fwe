#ifndef FWE_XOVER_H
#define FWE_XOVER_H

#include <stdbool.h>
#include <stdint.h>

/* The sub crossover: an LR4 (two cascaded 2nd-order Butterworth sections) low pass for the subs
 * and the matching high pass for the mains, plus each sub's level and delay. The coefficients
 * and the per-sample filter are pure logic (core/), tested on the host; the second I2S port and
 * the delay line are the ESP-IDF side's job. */

#define FWE_XOVER_MIN_HZ 40.0f       /* the crossover range the web app offers */
#define FWE_XOVER_MAX_HZ 200.0f
#define FWE_XOVER_MIN_LEVEL_MB (-6000) /* a sub's level, in millibels */
#define FWE_XOVER_MAX_LEVEL_MB 1200
#define FWE_XOVER_MAX_DELAY_US 20000u /* 20 ms, about 7 m of path difference */

/* One biquad, transposed direct form II, normalised so a0 is 1. */
typedef struct {
    float b0, b1, b2, a1, a2;
    float z1, z2;
} fwe_biquad_t;

/* An LR4: two identical Butterworth sections in series. */
typedef struct {
    fwe_biquad_t s[2];
} fwe_lr4_t;

typedef struct {
    float gain;              /* linear, from the level */
    uint32_t delay_samples;  /* rounded to the nearest sample */
} fwe_xover_sub_t;

/* Design an LR4 low pass (highpass false) or high pass at fc_hz for sample rate fs_hz, with the
 * bilinear transform pre-warped to fc. The state starts at zero. Returns 0, or -1 when fc is
 * outside FWE_XOVER_MIN_HZ..FWE_XOVER_MAX_HZ or not under fs/2 (then *out is left alone). */
int fwe_xover_lr4(float fc_hz, float fs_hz, bool highpass, fwe_lr4_t *out);

/* Filter one sample. */
float fwe_lr4_step(fwe_lr4_t *f, float x);

/* A sub's level (millibels) and delay (microseconds) at fs_hz. Returns 0, or -1 when either is
 * out of range (then *out is left alone). */
int fwe_xover_sub(int32_t level_mb, uint32_t delay_us, uint32_t fs_hz, fwe_xover_sub_t *out);

#endif
