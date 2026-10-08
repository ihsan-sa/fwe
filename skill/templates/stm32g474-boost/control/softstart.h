/* softstart.h - the soft-start reference ramp. With the switches off a
 * boost's output already sits at Vin (through the high-side body diode), so
 * the ramp starts from the measured Vin, where the feedforward duty is 0, and
 * slews the reference to the target. */
#ifndef SOFTSTART_H
#define SOFTSTART_H

typedef struct {
    float ref_v, target_v, slew_v_per_s;
    int done;
} softstart_t;

void ss_start(softstart_t *s, float vin_v, float target_v, float slew_v_per_s);
/* Advance by dt seconds; returns the reference. */
float ss_step(softstart_t *s, float dt);

#endif
