#include <assert.h>
#include <complex.h>
#include <math.h>
#include <stdio.h>

#include "fwe_xover.h"

#define FS 48000.0f
#define PI 3.14159265358979323846

/* H(e^jw) of the LR4 at f, from its coefficients */
static double complex response(const fwe_lr4_t *f, double hz)
{
    double complex z1 = cexp(-I * 2.0 * PI * hz / FS), h = 1.0;
    for (int i = 0; i < 2; i++) {
        const fwe_biquad_t *s = &f->s[i];
        h *= (s->b0 + s->b1 * z1 + s->b2 * z1 * z1) / (1.0 + s->a1 * z1 + s->a2 * z1 * z1);
    }
    return h;
}

static double db(double complex h)
{
    return 20.0 * log10(cabs(h));
}

static void test_lr4_at_80hz(void)
{
    fwe_lr4_t lp, hp;
    assert(fwe_xover_lr4(80.0f, FS, false, &lp) == 0);
    assert(fwe_xover_lr4(80.0f, FS, true, &hp) == 0);
    /* both -6 dB at the crossover, in phase */
    assert(fabs(db(response(&lp, 80.0)) + 6.02) < 0.05);
    assert(fabs(db(response(&hp, 80.0)) + 6.02) < 0.05);
    /* the passbands are flat, and 24 dB an octave: an octave out is -24.6 dB */
    assert(fabs(db(response(&lp, 10.0))) < 0.05);
    assert(fabs(db(response(&hp, 2000.0))) < 0.05);
    assert(fabs(db(response(&lp, 160.0)) + 24.61) < 0.05);
    assert(fabs(db(response(&hp, 40.0)) + 24.61) < 0.05);
    /* the LR4 property: the sub and the mains sum flat (an all pass) */
    for (double hz = 20.0; hz < 20000.0; hz *= 1.5) {
        assert(fabs(db(response(&lp, hz) + response(&hp, hz))) < 0.05);
    }
}

static void test_lr4_filters_samples(void)
{
    fwe_lr4_t lp, hp;
    assert(fwe_xover_lr4(80.0f, FS, false, &lp) == 0);
    assert(fwe_xover_lr4(80.0f, FS, true, &hp) == 0);
    float yl = 0.0f, yh = 0.0f;
    for (int n = 0; n < 48000; n++) {   /* a step, held for a second */
        yl = fwe_lr4_step(&lp, 1.0f);
        yh = fwe_lr4_step(&hp, 1.0f);
    }
    assert(fabsf(yl - 1.0f) < 1e-3f);   /* DC passes the sub */
    assert(fabsf(yh) < 1e-3f);          /* and not the mains */
    /* a 1 kHz sine: the sub's peak over the last cycles is about -88 dB */
    fwe_xover_lr4(80.0f, FS, false, &lp);
    float peak = 0.0f;
    for (int n = 0; n < 9600; n++) {
        float y = fwe_lr4_step(&lp, sinf(2.0f * (float)PI * 1000.0f * (float)n / FS));
        if (n >= 4800 && fabsf(y) > peak) {
            peak = fabsf(y);
        }
    }
    assert(20.0 * log10(peak) < -80.0);
}

static void test_lr4_refuses_out_of_range(void)
{
    fwe_lr4_t f = {0};
    assert(fwe_xover_lr4(30.0f, FS, false, &f) == -1);
    assert(fwe_xover_lr4(250.0f, FS, false, &f) == -1);
    assert(fwe_xover_lr4(120.0f, 200.0f, false, &f) == -1);  /* not under fs/2 */
    assert(f.s[0].b0 == 0.0f);
    assert(fwe_xover_lr4(40.0f, FS, true, &f) == 0 && fwe_xover_lr4(200.0f, FS, true, &f) == 0);
}

static void test_sub_level_and_delay(void)
{
    fwe_xover_sub_t s;
    assert(fwe_xover_sub(0, 0, 48000, &s) == 0);
    assert(fabsf(s.gain - 1.0f) < 1e-6f && s.delay_samples == 0);
    assert(fwe_xover_sub(-600, 2500, 48000, &s) == 0);    /* -6 dB, 2.5 ms */
    assert(fabsf(s.gain - 0.501187f) < 1e-4f && s.delay_samples == 120);
    assert(fwe_xover_sub(1200, 20000, 44100, &s) == 0);   /* the top of both ranges */
    assert(fabsf(s.gain - 3.981072f) < 1e-3f && s.delay_samples == 882);
    assert(fwe_xover_sub(0, 10, 44100, &s) == 0 && s.delay_samples == 0);   /* 0.441 rounds down */
    assert(fwe_xover_sub(0, 12, 44100, &s) == 0 && s.delay_samples == 1);   /* 0.529 rounds up */
    s.delay_samples = 7;
    assert(fwe_xover_sub(1300, 0, 48000, &s) == -1);
    assert(fwe_xover_sub(-6100, 0, 48000, &s) == -1);
    assert(fwe_xover_sub(0, 20001, 48000, &s) == -1);
    assert(fwe_xover_sub(0, 0, 0, &s) == -1);
    assert(s.delay_samples == 7);
}

int main(void)
{
    test_lr4_at_80hz();
    test_lr4_filters_samples();
    test_lr4_refuses_out_of_range();
    test_sub_level_and_delay();
    printf("fwe_xover: all tests passed\n");
    return 0;
}
