/* fw_config.h - per-board tunables. Edit freely; this file is not generated.
 * Pins and analog scaling come from gen/board_pins.h, never from here. */
#ifndef FW_CONFIG_H
#define FW_CONFIG_H

#define PWM_FREQ_HZ      20000u  /* center-aligned switching frequency */
#define DEADTIME_NS      100u    /* MCU dead time, on top of the driver's own */
#define I_TRIP_A         20.0f   /* hardware comparator trip (positive current) */
#define I_LIMIT_A        15.0f   /* software over-current limit, any phase, |i| */
#define VBUS_OV_V        30.0f   /* bus overvoltage trip */
#define VBUS_UV_V        9.0f    /* bus undervoltage trip */
#define MAX_DUTY         0.95f   /* duty cap, leaves bootstrap refresh time */
#define UART_BAUD        115200u
#define CONSOLE_LINE_MAX 96u     /* longest accepted command line, bytes */

#define HW_TRIP_ENABLE   1       /* COMP1/2/4 + DAC3 -> TIM1 break (see src/pwm.c) */
#define OFFSET_SAMPLES   256u    /* ADC samples per current-offset calibration */
#define OFFSET_TOL_V     0.15f   /* accepted offset distance from the nominal REF */
#define IWDG_TIMEOUT_MS  500u    /* watchdog reset if the main loop stalls */
#define STATUS_BLINK_MS  500u    /* status LED half-period (armed: a quarter) */

#endif
