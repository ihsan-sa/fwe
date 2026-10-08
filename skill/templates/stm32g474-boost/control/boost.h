/* boost.h - digital output-voltage loop for a synchronous boost. Pure math:
 * the caller measures and writes the duty to the HRTIM.
 *
 * Duty is the main (low-side) switch's duty D; in continuous conduction
 * Vout = Vin / (1 - D). Each step adds a PI on the voltage error to the
 * feedforward D_ff = 1 - Vin / Vref, so the loop only trims. An average
 * inductor-current limit folds the duty back by k_ilim per amp over the limit
 * and holds the integrator from winding up while it does. The duty is
 * clamped to [0, d_max]. */
#ifndef BOOST_H
#define BOOST_H

#include "pi.h"

typedef struct {
    pi_t v;          /* voltage PI; output is a duty trim */
    float d_max;     /* largest low-side duty */
    float i_limit_a; /* average inductor-current limit */
    float k_ilim;    /* duty taken off per amp over i_limit_a */
    int limiting;    /* the last step was current-limited */
} boost_ctl_t;

void boost_init(boost_ctl_t *c, float kp, float ki, float dt, float d_max,
                float i_limit_a, float k_ilim);
void boost_reset(boost_ctl_t *c);
/* 1 - vin / vref clamped to [0, d_max]; 0 when vref <= vin (a boost cannot buck). */
float boost_ff(float vin_v, float vref_v, float d_max);
float boost_step(boost_ctl_t *c, float vref_v, float vout_v, float vin_v, float il_a);

#endif
