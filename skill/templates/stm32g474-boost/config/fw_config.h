/* fw_config.h - per-board tunables of the HRTIM boost firmware. Edit freely;
 * this file is not generated. Pins, sense scaling and the comparator ->
 * HRTIM fault routing come from gen/board_pins.h, never from here.
 *
 * Every number cites where it comes from: a board document (path:line in the
 * board workspace) or "fwe default" with the reason, when the documents do
 * not give it. Re-check the cited lines when the board's documents change. */
#ifndef FW_CONFIG_H
#define FW_CONFIG_H

/* --- power stage --- */
#define PWM_FREQ_HZ      1000000u /* research/power-stage.md:19 "fsw = 1.00 MHz" */
#define DEADTIME_NS      10u      /* research/power-stage.md:42 "dead time 10 ns" (both edges) */
#define HRTIM_FHRTIM_HZ  170000000u /* fHRTIM = SYSCLK = APB2 (src/clock.c); x32 DLL gives 184 ps */
#define VOUT_TARGET_V    48.0f    /* requirements.md:9 "regulated 48 V DC out" */
#define D_MAX            0.82f    /* fwe default: 12 -> 48 V needs D 0.75 (requirements.md:63); 0.82 covers losses, caps the boost ratio at ~5.6 */

/* --- protection: hardware (comparator -> HRTIM fault, no firmware in the path) --- */
#define VOUT_OV_V        55.0f    /* architecture/power_tree.md:7, research/power-stage.md:118 "COMP3 -> HRTIM fault at 55 V" */
#define I_TRIP_A         17.0f    /* research/power-stage.md:94-95 "OCP trip 17 A = 2.50 V"; an average trip, not cycle-by-cycle (:96-97) */
#define COMP_HYST        2u       /* fwe default: COMPx_CSR HYST = 010 (~20 mV, DS), so INA240/divider noise does not chatter the trip */
#define FAULT_FILTER     3u       /* fwe default: FLTxF = 0011, fHRTIM N = 8 (~47 ns, RM0440 28.5.76): rejects switching-edge glitches; the trip is an average one anyway */

/* --- protection: software (checked on every control sample) --- */
#define I_LIMIT_A        14.5f    /* fwe default: average inductor-current fold-back above the 13.2 A full-load input (requirements.md:20), under the 17 A trip */
#define K_ILIM           0.02f    /* fwe default: duty taken off per amp over I_LIMIT_A; 1 A over at 12 V in is ~2 % of D */
#define VIN_UV_V         10.5f    /* fwe default: 12-24 V operating (requirements.md:34); 1.5 V under 12 V for input sag at 13 A */
#define VIN_OV_V         27.0f    /* fwe default: above the 24 V operating max, under the 30 V survive level (requirements.md:34) */
#define T_DERATE_C       95.0f    /* research/power-stage.md:155-156, architecture/blocks.md:40 "NTC > 95 C derates to 100 W" */
#define P_DERATE_W       100.0f   /* research/power-stage.md:155-156 (input power limit while derated) */
#define T_SHUTDOWN_C     110.0f   /* research/power-stage.md:156 "NTC > 110 C shuts down" */

/* --- control loop --- */
#define CTRL_DIV         10u      /* fwe default: HRTIM ADC post-scaler, one sample per 10 periods = 100 kHz loop: ~5 us of ADC work in a 10 us slot */
#define CTRL_KP          0.002f   /* fwe default: duty per volt of error; the feedforward 1 - Vin/Vref carries the operating point, the PI only trims. Tune on the bench */
#define CTRL_KI          20.0f    /* fwe default: duty per volt-second; slow (~1 ms to trim 2 %), so it cannot fight the soft start */
#define SS_SLEW_V_PER_S  3000.0f  /* fwe default: ramp from Vout ~ Vin (research/power.md:28) to 48 V in ~12 ms at 12 V in, so the output-capacitor charge current stays small */
#define ADC_STALE_MS     5u       /* fwe default: no control sample for this long while switching = the loop has stopped (trip "adc") */

/* --- fan (requirements.md:47-55, owner 2026-10-08; supersedes research/power-stage.md:153) --- */
#define FAN_PWM_HZ       50u      /* requirements.md:54 "~25-100 Hz, or full-on"; 50 Hz is mid-range */
#define FAN_ON_C         80.0f    /* research/power-stage.md:155 "NTC > 80 C" turns the fan on */

/* --- console, watchdog --- */
#define UART_BAUD        115200u
#define CONSOLE_LINE_MAX 96u      /* longest accepted command line, bytes */
#define IWDG_TIMEOUT_MS  500u     /* watchdog reset if the main loop stalls */

#endif
