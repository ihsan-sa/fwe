/* pi.h - PI controller with anti-windup.
 * The integrator is clamped to [out_min, out_max] and does not integrate
 * further into a saturated output (conditional integration), so it leaves
 * saturation as soon as the error changes sign. */
#ifndef PI_H
#define PI_H

typedef struct {
    float kp, ki, dt;       /* gains; ki in 1/s, dt in s */
    float out_min, out_max;
    float integ;            /* integrator state (output units) */
} pi_t;

void pi_init(pi_t *p, float kp, float ki, float dt, float out_min, float out_max);
void pi_reset(pi_t *p);
float pi_step(pi_t *p, float err);

#endif
