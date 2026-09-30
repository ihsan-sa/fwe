/* main.c - bring-up firmware: safe init order, then the main loop.
 * Order matters (design.md, safety defaults): gate pins low as GPIO first,
 * clocks, TIM1 with MOE = 0 and idle-low outputs, then the gate pins go to
 * the timer; LEDs, console, ADC calibration and offsets with the bridge off,
 * the hardware trip, the watchdog; then measure -> check -> console forever. */
#include "app.h"
#include "sense.h"

app_t g_app;

int main(void)
{
    const char *cause = board_reset_cause();

    board_gpio_clocks();
    pwm_gate_pins_safe();          /* 1. INHx/INLx low before anything else */
    clock_init();                  /* 2. 170 MHz, SysTick */
    pwm_init();                    /* 3. TIM1 running, MOE = 0, outputs idle low */
    pwm_gate_pins_af();            /* 4. pins handed to TIM1 (still low) */
    board_init();                  /* 5. LEDs, button */
    console_init();
    console_boot(cause);

    safety_init();
    if (adc_init() == 0) adc_calibrate_offsets(); /* bridge is off: MOE = 0 */

    /* the trip voltage uses the highest calibrated zero-current voltage */
    float ref = g_app.i_ref_v[0];
    if (g_app.i_ref_v[1] > ref) ref = g_app.i_ref_v[1];
    if (g_app.i_ref_v[2] > ref) ref = g_app.i_ref_v[2];
    g_app.hw_trip_ok = pwm_hw_trip_init(sense_current_to_v(I_TRIP_A, ref, ISENSE_A_GAIN, ISENSE_A_SHUNT_OHM)) == 0;
    if (HW_TRIP_ENABLE && !g_app.hw_trip_ok) console_evt_fault(fault_latch(&g_app.faults, FAULT_OC_HW));

    iwdg_init();
    for (;;) {
        iwdg_kick();
        safety_poll();
        console_poll();
        board_poll();
    }
}
