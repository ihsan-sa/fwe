/* safety.c - the fault wiring, run on every main-loop pass: measure, check,
 * latch; a new fault clears MOE at once, lights the fault LED (board_poll
 * follows the latch) and emits one EVT line. */
#include "app.h"

static const fault_limits_t k_limits = { VBUS_OV_V, VBUS_UV_V, I_TRIP_A, I_LIMIT_A };

void safety_init(void)
{
    fault_init(&g_app.faults);
}

uint32_t safety_active_now(void)
{
    uint32_t a = fault_check(&k_limits, g_app.vbus_v, g_app.i_a);
    if (pwm_hw_trip_active()) a |= FAULT_OC_HW;
    return a;
}

void safety_poll(void)
{
    adc_sample();
    uint32_t active = safety_active_now();
    g_app.active = active;
    uint32_t fresh = fault_update(&g_app.faults, active);
    if (pwm_break_flag()) fresh |= fault_latch(&g_app.faults, FAULT_OC_HW);
    if (fault_is_latched(&g_app.faults) && (g_app.armed || pwm_is_armed())) pwm_disarm();
    if (g_app.armed && !pwm_is_armed()) pwm_disarm(); /* hardware dropped MOE */
    if (fresh) console_evt_fault(fresh);
}
