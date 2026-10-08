/* main.c - boost firmware: safe init order, then the main loop.
 * Order matters (design.md, safety defaults): gate pins low as GPIO first,
 * clocks, the HRTIM with both outputs disabled (inactive idle and fault
 * states), then the gate pins go to the HRTIM; console; comparators and
 * their DAC thresholds, then the HRTIM fault inputs that listen to them; the
 * fan; the ADC last, because its interrupt is the control loop; the
 * watchdog; then supervise -> console -> fan forever. Nothing switches until
 * an "arm" or "duty" command passes the checks in safety.c. */
#include "app.h"

app_t g_app;

int main(void)
{
    const char *cause = board_reset_cause();

    board_gpio_clocks();
    hrtim_gate_pins_safe();        /* 1. PWM_LO/PWM_HI low before anything else */
    clock_init();                  /* 2. 170 MHz, SysTick */
    int hr = hrtim_init();         /* 3. DLL locked, Timer A counting, outputs disabled */
    if (hr == 0)
        hrtim_gate_pins_af();      /* 4. pins handed to the HRTIM (still low); a
                                    * failed HRTIM leaves them low as GPIO */
    console_init();

    safety_init();
    int cmp = comp_init();         /* 5. thresholds, comparators locked */
    int flt = hr == 0 ? hrtim_faults_init() : -1; /* 6. FLTn on the comparators */
    /* cmp == -3: a comparator is already high. The trips are armed, and the
     * FLTn flag it raises latches in safety_poll, so arm and clear refuse
     * until it drops; only a setup failure leaves the hardware not ok */
    g_app.hw_ok = hr == 0 && (cmp == 0 || cmp == -3) && flt == 0;
    console_boot(cause);
    fan_init();
    adc_init();                    /* 7. the control sample starts */

    iwdg_init();
    for (;;) {
        iwdg_kick();
        safety_poll();
        console_poll();
        fan_poll();
    }
}
