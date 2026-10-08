/* app.h - shared declarations of the HRTIM boost firmware (src/ only). */
#ifndef APP_H
#define APP_H

#include <stdint.h>
#include "stm32g4xx.h"
#include "board_pins.h"
#include "fw_config.h"
#include "trip.h"

#ifndef FW_VERSION
#define FW_VERSION "0.0.0"
#endif
#ifndef FW_STAGE
#define FW_STAGE "boost"
#endif

/* The pin map must name both hardware trips: firmware never guesses which
 * comparator or fault input a board uses. */
#if !defined(TRIP_OVP_COMP) || !defined(TRIP_OVP_FLT) || !defined(TRIP_OCP_COMP) || !defined(TRIP_OCP_FLT)
#error "gen/board_pins.h has no TRIP_OVP_* / TRIP_OCP_* fault routes: re-run pinmap.py"
#endif
#if !defined(PIN_PWM_LO_HRTIM_TIMER) || PIN_PWM_LO_HRTIM_TIMER != 0u || PIN_PWM_LO_HRTIM_OUT != 1u \
    || PIN_PWM_HI_HRTIM_TIMER != 0u || PIN_PWM_HI_HRTIM_OUT != 2u
#error "this template drives the main switch on HRTIM1 TA1 and its complement on TA2"
#endif

/* MODE_OPEN: a fixed bench duty from the console, no regulation. */
typedef enum { MODE_OFF = 0, MODE_SOFTSTART, MODE_RUN, MODE_OPEN } ctl_mode_t;

/* Everything the control sample measures and the console reports. Written
 * by the ADC interrupt; the main loop reads it and changes the mode and the
 * latch only with the interrupt masked. */
typedef struct {
    uint16_t raw[4];             /* JDR1..4: ISNS, VOUT, VIN, NTC */
    float il_a, vout_v, vin_v, temp_c;
    float duty, vref_v;
    volatile ctl_mode_t mode;
    volatile uint32_t samples;   /* control samples taken (ADC interrupts) */
    trip_state_t trips;
    uint32_t active;             /* software trip conditions on the last sample */
    volatile uint32_t evt;       /* trips latched in the interrupt, not yet reported */
    int derated;                 /* NTC over T_DERATE_C: current limit cut to P_DERATE_W */
    int hw_ok;                   /* DLL locked, comparators and faults armed */
    int adc_ok;
} app_t;

extern app_t g_app;

/* clock.c */
void clock_init(void);
uint32_t millis(void);
void delay_us(uint32_t us);
int clock_is_pll_170(void);

/* board.c: GPIO helpers, reset cause, watchdog */
enum { GPIO_IN = 0u, GPIO_OUT = 1u, GPIO_AF = 2u, GPIO_ANALOG = 3u };
void gpio_mode(GPIO_TypeDef *g, uint32_t pin, uint32_t mode);
void gpio_af(GPIO_TypeDef *g, uint32_t pin, uint32_t af);
void gpio_write(GPIO_TypeDef *g, uint32_t pin, int on);
void board_gpio_clocks(void);
const char *board_reset_cause(void);
void iwdg_init(void);
void iwdg_kick(void);

/* hrtim.c: Timer A complementary PWM, dead time, faults, ADC trigger */
void hrtim_gate_pins_safe(void);
int hrtim_init(void);
int hrtim_faults_init(void);         /* after comp_init: FLTn from the comparators */
void hrtim_gate_pins_af(void);
uint32_t hrtim_period(void);
void hrtim_set_duty(float d);
void hrtim_outputs_on(void);
void hrtim_outputs_off(void);
int hrtim_outputs_are_on(void);
uint32_t hrtim_fault_flags(void);   /* TRIP_*_HW bits whose FLTn flag is set */
void hrtim_fault_flags_clear(void);
int hrtim_dll_ready(void);

/* comp.c: comparators + DAC thresholds */
int comp_init(void);
uint32_t comp_active(void);         /* TRIP_*_HW bits whose comparator output is high */
float comp_threshold_v(uint32_t trip_bit);

/* adc.c: ADC1 injected sequence on the HRTIM trigger */
int adc_init(void);
void adc_convert(void);             /* raw[] -> engineering units */

/* safety.c: the control sample and the main-loop supervision */
void safety_init(void);
void safety_sample(void);           /* ADC interrupt: measure -> trip -> control */
void safety_poll(void);             /* main loop: HW fault flags, stale loop, events */
uint32_t safety_active_now(void);   /* software conditions + comparators high */
int safety_arm(void);
int safety_open(float d);
void safety_disarm(void);
const char *safety_mode_name(void);

/* fan.c */
void fan_init(void);
void fan_poll(void);
void fan_override(int mode);        /* -1 auto, else 0..100 % */
float fan_duty(void);
int fan_is_auto(void);

/* console.c */
void console_init(void);
void console_boot(const char *reset_cause);
void console_poll(void);
void console_evt_trip(uint32_t fresh);

#endif
