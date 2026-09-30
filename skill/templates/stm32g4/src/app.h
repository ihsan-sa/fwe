/* app.h - shared declarations of the bring-up firmware (src/ only). */
#ifndef APP_H
#define APP_H

#include <stdint.h>
#include "stm32g4xx.h"
#include "board_pins.h"
#include "fw_config.h"
#include "fault.h"

#ifndef FW_VERSION
#define FW_VERSION "0.0.0"
#endif
#ifndef FW_STAGE
#define FW_STAGE "bringup"
#endif

/* Everything the loop measures and the console reports. */
typedef struct {
    uint16_t raw_vbus, raw_i[3];
    float vbus_v, i_a[3];
    float i_ref_v[3];     /* calibrated INA240 zero-current voltage per phase */
    int offsets_ok;
    int adc_ok;
    int hw_trip_ok;       /* comparators + DAC3 armed onto the TIM1 break */
    int armed;
    float duty[3];
    fault_state_t faults;
    uint32_t active;      /* fault conditions active on the last pass */
} app_t;

extern app_t g_app;

/* clock.c */
void clock_init(void);
uint32_t millis(void);
void delay_us(uint32_t us);
int clock_is_pll_170(void);

/* board.c: GPIO helpers, LEDs, button, reset cause, watchdog */
enum { GPIO_IN = 0u, GPIO_OUT = 1u, GPIO_AF = 2u, GPIO_ANALOG = 3u };
void gpio_mode(GPIO_TypeDef *g, uint32_t pin, uint32_t mode);
void gpio_af(GPIO_TypeDef *g, uint32_t pin, uint32_t af);
void gpio_write(GPIO_TypeDef *g, uint32_t pin, int on);
int gpio_read(GPIO_TypeDef *g, uint32_t pin);
void board_gpio_clocks(void);
void board_init(void);
void board_poll(void);
enum { LED_AUTO = -1, LED_OFF = 0, LED_ON = 1 };
void board_led_override(int fault_led, int mode);
const char *board_reset_cause(void);
void iwdg_init(void);
void iwdg_kick(void);

/* pwm.c: TIM1 complementary PWM, break, arm/disarm */
void pwm_gate_pins_safe(void);
void pwm_init(void);
void pwm_gate_pins_af(void);
int pwm_hw_trip_init(float v_trip);
int pwm_hw_trip_active(void);
int pwm_break_flag(void);
void pwm_break_flag_clear(void);
int pwm_arm(void);
void pwm_disarm(void);
int pwm_is_armed(void);
void pwm_set_duty(const float d[3]);

/* adc.c */
int adc_init(void);
void adc_sample(void);
int adc_calibrate_offsets(void);

/* safety.c */
void safety_init(void);
void safety_poll(void);
uint32_t safety_active_now(void);

/* console.c */
void console_init(void);
void console_boot(const char *reset_cause);
void console_poll(void);
void console_evt_fault(uint32_t fresh);
void console_evt_button(int level);

#endif
