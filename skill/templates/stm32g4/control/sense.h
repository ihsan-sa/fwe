/* sense.h - analog front-end scaling. Pure C: every board constant is an
 * argument (the firmware passes the values from gen/board_pins.h). */
#ifndef SENSE_H
#define SENSE_H

#include <stdint.h>

#define SENSE_ADC_FULL_SCALE 4095.0f /* 12-bit */

/* ADC counts -> volts at the pin, for an ADC reference of vref volts. */
float sense_counts_to_v(uint32_t counts, float vref);
/* Current-sense amplifier (INA240-style): i = (v - ref_v) / (gain * shunt). */
float sense_current_a(float v, float ref_v, float gain, float shunt_ohm);
/* Inverse: the pin voltage a current produces (used for a trip threshold). */
float sense_current_to_v(float i_a, float ref_v, float gain, float shunt_ohm);
/* Bus voltage from a divider: v_bus = v_pin * ratio. */
float sense_vbus_v(float v_pin, float ratio);

/* Running mean for offset calibration (bridge off, so the true current is 0). */
typedef struct { float sum; uint32_t n; } sense_avg_t;
void sense_avg_reset(sense_avg_t *a);
void sense_avg_add(sense_avg_t *a, float x);
/* Mean of the samples, or fallback when there are none. */
float sense_avg_mean(const sense_avg_t *a, float fallback);
/* An offset is accepted only within tol volts of the nominal reference. */
int sense_offset_ok(float measured_v, float nominal_v, float tol_v);

#endif
