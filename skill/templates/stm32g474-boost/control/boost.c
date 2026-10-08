#include "boost.h"

static float clampf(float x, float lo, float hi)
{
    return x < lo ? lo : (x > hi ? hi : x);
}

void boost_init(boost_ctl_t *c, float kp, float ki, float dt, float d_max,
                float i_limit_a, float k_ilim)
{
    pi_init(&c->v, kp, ki, dt, -d_max, d_max);
    c->d_max = d_max;
    c->i_limit_a = i_limit_a;
    c->k_ilim = k_ilim;
    c->limiting = 0;
}

void boost_reset(boost_ctl_t *c)
{
    pi_reset(&c->v);
    c->limiting = 0;
}

float boost_ff(float vin_v, float vref_v, float d_max)
{
    if (!(vref_v > vin_v) || !(vin_v > 0.0f))
        return 0.0f;
    return clampf(1.0f - vin_v / vref_v, 0.0f, d_max);
}

float boost_step(boost_ctl_t *c, float vref_v, float vout_v, float vin_v, float il_a)
{
    float err = vref_v - vout_v;
    float over = il_a - c->i_limit_a;
    float trim;
    c->limiting = over > 0.0f;
    if (c->limiting && err > 0.0f)
        trim = c->v.kp * err + c->v.integ; /* hold the integrator */
    else
        trim = pi_step(&c->v, err);
    float d = boost_ff(vin_v, vref_v, c->d_max) + trim;
    if (c->limiting)
        d -= c->k_ilim * over;
    if (!(d == d))
        return 0.0f; /* NaN measurement: switch nothing */
    return clampf(d, 0.0f, c->d_max);
}
