#include "fwe_xover.h"

#include <math.h>
#include <string.h>

#define BUTTERWORTH_Q 0.70710678f
#define PI_F 3.14159265f

static void butterworth(float k, bool highpass, fwe_biquad_t *s)
{
    float norm = 1.0f / (1.0f + k / BUTTERWORTH_Q + k * k);
    s->b0 = highpass ? norm : k * k * norm;
    s->b1 = highpass ? -2.0f * s->b0 : 2.0f * s->b0;
    s->b2 = s->b0;
    s->a1 = 2.0f * (k * k - 1.0f) * norm;
    s->a2 = (1.0f - k / BUTTERWORTH_Q + k * k) * norm;
    s->z1 = s->z2 = 0.0f;
}

int fwe_xover_lr4(float fc_hz, float fs_hz, bool highpass, fwe_lr4_t *out)
{
    if (!(fc_hz >= FWE_XOVER_MIN_HZ && fc_hz <= FWE_XOVER_MAX_HZ && fc_hz < fs_hz / 2.0f)) {
        return -1;
    }
    float k = tanf(PI_F * fc_hz / fs_hz);
    butterworth(k, highpass, &out->s[0]);
    out->s[1] = out->s[0];
    return 0;
}

static float biquad_step(fwe_biquad_t *s, float x)
{
    float y = s->b0 * x + s->z1;
    s->z1 = s->b1 * x - s->a1 * y + s->z2;
    s->z2 = s->b2 * x - s->a2 * y;
    return y;
}

float fwe_lr4_step(fwe_lr4_t *f, float x)
{
    return biquad_step(&f->s[1], biquad_step(&f->s[0], x));
}

int fwe_xover_sub(int32_t level_mb, uint32_t delay_us, uint32_t fs_hz, fwe_xover_sub_t *out)
{
    if (level_mb < FWE_XOVER_MIN_LEVEL_MB || level_mb > FWE_XOVER_MAX_LEVEL_MB ||
        delay_us > FWE_XOVER_MAX_DELAY_US || fs_hz == 0) {
        return -1;
    }
    out->gain = powf(10.0f, (float)level_mb / 2000.0f);
    out->delay_samples = (uint32_t)(((uint64_t)delay_us * fs_hz + 500000u) / 1000000u);
    return 0;
}

int fwe_delay_init(fwe_delay_t *d, uint32_t samples)
{
    if (samples > FWE_XOVER_DELAY_CAP) {
        return -1;
    }
    memset(d->buf, 0, sizeof d->buf);
    d->len = samples;
    d->pos = 0;
    return 0;
}

float fwe_delay_step(fwe_delay_t *d, float x)
{
    if (d->len == 0) {
        return x;
    }
    float y = d->buf[d->pos];
    d->buf[d->pos] = x;
    d->pos = d->pos + 1 == d->len ? 0 : d->pos + 1;
    return y;
}
