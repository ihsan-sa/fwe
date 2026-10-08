/* scale.h - unit conversions between the board and the MCU. Pure math, so the
 * host tests cover it: ADC counts to volts, amps and degrees, the DAC code of
 * a comparator threshold, and the HRTIM counts of a frequency, dead time and
 * duty (RM0440 section 28.3). A reading that cannot be converted is NaN, so
 * trip_check() trips on it. */
#ifndef SCALE_H
#define SCALE_H

#include <stdint.h>

#define ADC_FULL      4095.0f
#define HR_CMP_MIN    0x60u  /* RM0440 28.3.4: compare/period >= 3 fHRTIM periods at CKPSC = 0 */
#define HR_DT_MAX     511u   /* DTR/DTF[8:0] */

float scale_counts_v(uint32_t raw, float vref);
/* Inductor current from the INA240 output: (v - ref) / (gain * shunt). */
float scale_current_a(float v_pin, float ref_v, float gain, float shunt_ohm);
/* NTC to ground with a pull-up to vdd, beta model. NaN outside 2..98 % of vdd
 * (open or shorted sensor), so a broken NTC trips instead of reading cold. */
float scale_ntc_c(float v_pin, float vdd, float pullup_ohm, float r25_ohm, float beta);
/* 12-bit DAC code for v_pin, rounded and clamped to 0..4095. */
uint32_t scale_dac_code(float v_pin, float vref);

/* HRTIM period for fsw: fHRTIM x 32 / 2^ckpsc / fsw, rounded (RM0440 28.3.3). */
uint32_t hr_period(uint32_t fhrtim_hz, uint32_t fsw_hz, uint32_t ckpsc);
/* Dead-time counts, rounded up: tDTG = 2^dtprsc x tHRTIM / 8 (RM0440 28.3.4,
 * Table 237); clamped to HR_DT_MAX. */
uint32_t hr_deadtime(uint32_t ns, uint32_t fhrtim_hz, uint32_t dtprsc);
/* CMP1 for duty d: clamped to [0, d_max]; a pulse shorter than HR_CMP_MIN
 * (or a NaN duty) is 0, the null-duty value that skips the pulse (RM0440
 * 28.3.4 "Null duty cycle exception case"). */
uint32_t hr_duty_cmp(float d, float d_max, uint32_t per);
/* The ADC trigger compare: mid on-time (cmp1 / 2), at least HR_CMP_MIN;
 * mid-period when there is no pulse. */
uint32_t hr_adc_cmp(uint32_t cmp1, uint32_t per);

#endif
