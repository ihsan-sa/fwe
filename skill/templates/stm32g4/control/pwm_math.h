/* pwm_math.h - timer arithmetic for a center-aligned complementary PWM.
 * Pure C so the host tests cover it; src/pwm.c writes the results. */
#ifndef PWM_MATH_H
#define PWM_MATH_H

#include <stdint.h>

/* Auto-reload for center-aligned mode: ARR = f_tim / (2 * f_pwm). */
uint32_t pwm_arr_center(uint32_t f_tim_hz, uint32_t f_pwm_hz);
/* Dead time in timer ticks (rounded up) for ns at f_tim_hz. */
uint32_t pwm_deadtime_ticks(uint32_t ns, uint32_t f_tim_hz);
/* STM32 advanced-timer BDTR.DTG encoding of at least `ticks` tDTS periods
 * (CKD = 0). Saturates at the largest encodable dead time (1008 ticks). */
uint8_t pwm_dtg_encode(uint32_t ticks);
/* Ticks a DTG value stands for (the inverse, for tests and reports). */
uint32_t pwm_dtg_ticks(uint8_t dtg);
/* Duty 0..1 -> compare value, clamped to 0..max_duty (NaN -> 0). */
uint32_t pwm_duty_to_ccr(float duty, float max_duty, uint32_t arr);

#endif
