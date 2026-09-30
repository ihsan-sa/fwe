#include "foc.h"

foc_ab_t foc_clarke(float a, float b)
{
    foc_ab_t r = { a, (a + 2.0f * b) * FOC_INV_SQRT3 };
    return r;
}

foc_abc_t foc_inv_clarke(foc_ab_t v)
{
    foc_abc_t r;
    r.a = v.alpha;
    r.b = 0.5f * (-v.alpha + FOC_SQRT3 * v.beta);
    r.c = 0.5f * (-v.alpha - FOC_SQRT3 * v.beta);
    return r;
}

foc_dq_t foc_park(foc_ab_t v, float sin_t, float cos_t)
{
    foc_dq_t r = { v.alpha * cos_t + v.beta * sin_t, -v.alpha * sin_t + v.beta * cos_t };
    return r;
}

foc_ab_t foc_inv_park(foc_dq_t v, float sin_t, float cos_t)
{
    foc_ab_t r = { v.d * cos_t - v.q * sin_t, v.d * sin_t + v.q * cos_t };
    return r;
}

static float clampf(float x, float lo, float hi)
{
    if (!(x >= lo)) return lo; /* also catches NaN */
    return x > hi ? hi : x;
}

foc_abc_t foc_svpwm(foc_ab_t v, float vbus, float max_duty)
{
    foc_abc_t d = { 0.5f, 0.5f, 0.5f };
    if (vbus > 0.0f) {
        foc_abc_t p = foc_inv_clarke(v);
        float mx = p.a, mn = p.a;
        if (p.b > mx) mx = p.b;
        if (p.c > mx) mx = p.c;
        if (p.b < mn) mn = p.b;
        if (p.c < mn) mn = p.c;
        float off = -0.5f * (mx + mn);
        d.a = 0.5f + (p.a + off) / vbus;
        d.b = 0.5f + (p.b + off) / vbus;
        d.c = 0.5f + (p.c + off) / vbus;
    }
    d.a = clampf(d.a, 0.0f, max_duty);
    d.b = clampf(d.b, 0.0f, max_duty);
    d.c = clampf(d.c, 0.0f, max_duty);
    return d;
}
