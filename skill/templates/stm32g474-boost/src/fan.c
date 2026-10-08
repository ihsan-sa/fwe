/* fan.c - the heatsink fan on TIM4_CH1 (PB6, AF2), PWM at FAN_PWM_HZ.
 *
 * TIM4 counts at 1 MHz (PCLK1 = 170 MHz, PSC = 169), so ARR = 1 MHz /
 * FAN_PWM_HZ - 1 and CCR1 is the on-time in us. PWM mode 1, preloaded.
 * Auto: full speed while the converter switches, above FAN_ON_C, or when the
 * NTC reading is lost (NaN); off otherwise. The console can force a duty. */
#include "app.h"

#define FAN_TICK_HZ 1000000u
#define FAN_ARR (FAN_TICK_HZ / FAN_PWM_HZ - 1u)

#if FAN_ARR > 0xFFFFu
#error "FAN_PWM_HZ too low for TIM4's 16-bit counter at 1 MHz"
#endif

static int s_override = -1;
static float s_duty;

static void fan_set(float d)
{
    s_duty = d;
    TIM4->CCR1 = (uint32_t)(d * (float)(FAN_ARR + 1u) + 0.5f);
}

void fan_init(void)
{
    RCC->APB1ENR1 |= RCC_APB1ENR1_TIM4EN;
    (void)RCC->APB1ENR1;
    TIM4->CR1 = 0u;
    TIM4->PSC = SystemCoreClock / FAN_TICK_HZ - 1u;
    TIM4->ARR = FAN_ARR;
    TIM4->CCR1 = 0u;
    TIM4->CCMR1 = TIM_CCMR1_OC1M_1 | TIM_CCMR1_OC1M_2 | TIM_CCMR1_OC1PE; /* PWM mode 1 */
    TIM4->CCER = TIM_CCER_CC1E;
    TIM4->EGR = TIM_EGR_UG;
    TIM4->CR1 = TIM_CR1_ARPE | TIM_CR1_CEN;
    gpio_af(PIN_FAN_PWM_PORT, PIN_FAN_PWM_PIN, PIN_FAN_PWM_AF);
    gpio_mode(PIN_FAN_PWM_PORT, PIN_FAN_PWM_PIN, GPIO_AF);
}

void fan_poll(void)
{
    if (s_override >= 0) { fan_set((float)s_override / 100.0f); return; }
    float t = g_app.temp_c;
    int hot = !(t < FAN_ON_C);   /* NaN counts as hot */
    fan_set(hot || g_app.mode != MODE_OFF ? 1.0f : 0.0f);
}

void fan_override(int mode)
{
    s_override = mode < 0 ? -1 : mode > 100 ? 100 : mode;
    fan_poll();
}

float fan_duty(void)
{
    return s_duty;
}

int fan_is_auto(void)
{
    return s_override < 0;
}
