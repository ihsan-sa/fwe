#include "pi.h"

void pi_init(pi_t *p, float kp, float ki, float dt, float out_min, float out_max)
{
    p->kp = kp;
    p->ki = ki;
    p->dt = dt;
    p->out_min = out_min;
    p->out_max = out_max;
    p->integ = 0.0f;
}

void pi_reset(pi_t *p)
{
    p->integ = 0.0f;
}

float pi_step(pi_t *p, float err)
{
    float prop = p->kp * err;
    float out = prop + p->integ;
    /* integrate unless the output is saturated and the error pushes further */
    int sat_hi = out >= p->out_max && err > 0.0f;
    int sat_lo = out <= p->out_min && err < 0.0f;
    if (!sat_hi && !sat_lo) {
        p->integ += p->ki * p->dt * err;
        if (p->integ > p->out_max) p->integ = p->out_max;
        if (p->integ < p->out_min) p->integ = p->out_min;
    }
    out = prop + p->integ;
    if (out > p->out_max) out = p->out_max;
    if (out < p->out_min) out = p->out_min;
    return out;
}
