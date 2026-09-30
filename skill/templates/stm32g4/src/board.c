/* board.c - GPIO helpers, LEDs, user button, reset cause and the watchdog. */
#include "app.h"

void gpio_mode(GPIO_TypeDef *g, uint32_t pin, uint32_t mode)
{
    g->MODER = (g->MODER & ~(3u << (pin * 2u))) | (mode << (pin * 2u));
}

void gpio_af(GPIO_TypeDef *g, uint32_t pin, uint32_t af)
{
    uint32_t sh = (pin & 7u) * 4u;
    g->AFR[pin >> 3] = (g->AFR[pin >> 3] & ~(0xFu << sh)) | (af << sh);
}

void gpio_write(GPIO_TypeDef *g, uint32_t pin, int on)
{
    g->BSRR = on ? (1u << pin) : (1u << (pin + 16u));
}

int gpio_read(GPIO_TypeDef *g, uint32_t pin)
{
    return (int)((g->IDR >> pin) & 1u);
}

void board_gpio_clocks(void)
{
    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN | RCC_AHB2ENR_GPIOBEN | RCC_AHB2ENR_GPIOCEN
                  | RCC_AHB2ENR_GPIODEN | RCC_AHB2ENR_GPIOEEN | RCC_AHB2ENR_GPIOFEN
                  | RCC_AHB2ENR_GPIOGEN;
    (void)RCC->AHB2ENR;
}

static int s_led_mode[2] = { LED_AUTO, LED_AUTO }; /* [0] status, [1] fault */
static int s_btn_level, s_btn_count;
static uint32_t s_btn_ms;

void board_init(void)
{
#ifdef PIN_LED_STATUS_PORT
    gpio_write(PIN_LED_STATUS_PORT, PIN_LED_STATUS_PIN, 0);
    gpio_mode(PIN_LED_STATUS_PORT, PIN_LED_STATUS_PIN, GPIO_OUT);
#endif
#ifdef PIN_LED_FAULT_PORT
    gpio_write(PIN_LED_FAULT_PORT, PIN_LED_FAULT_PIN, 0);
    gpio_mode(PIN_LED_FAULT_PORT, PIN_LED_FAULT_PIN, GPIO_OUT);
#endif
#ifdef PIN_USER_SW_PORT
    gpio_mode(PIN_USER_SW_PORT, PIN_USER_SW_PIN, GPIO_IN); /* board provides the pull */
    s_btn_level = gpio_read(PIN_USER_SW_PORT, PIN_USER_SW_PIN);
#endif
}

void board_led_override(int fault_led, int mode)
{
    s_led_mode[fault_led ? 1 : 0] = mode;
}

void board_poll(void)
{
    uint32_t now = millis();
    uint32_t half = g_app.armed ? STATUS_BLINK_MS / 4u : STATUS_BLINK_MS;
    int status_on = s_led_mode[0] == LED_AUTO ? (int)((now / half) & 1u) : s_led_mode[0];
    int fault_on = s_led_mode[1] == LED_AUTO ? fault_is_latched(&g_app.faults) : s_led_mode[1];
#ifdef PIN_LED_STATUS_PORT
    gpio_write(PIN_LED_STATUS_PORT, PIN_LED_STATUS_PIN, status_on);
#endif
#ifdef PIN_LED_FAULT_PORT
    gpio_write(PIN_LED_FAULT_PORT, PIN_LED_FAULT_PIN, fault_on);
#endif
    (void)status_on;
    (void)fault_on;

#ifdef PIN_USER_SW_PORT
    /* 10 ms sampling, 3 equal samples = debounced; reports the raw level
     * because the button's polarity is the board's, not the firmware's */
    if (now - s_btn_ms >= 10u) {
        s_btn_ms = now;
        int lvl = gpio_read(PIN_USER_SW_PORT, PIN_USER_SW_PIN);
        s_btn_count = lvl != s_btn_level ? s_btn_count + 1 : 0;
        if (s_btn_count >= 3) {
            s_btn_level = lvl;
            s_btn_count = 0;
            console_evt_button(lvl);
        }
    }
#endif
}

const char *board_reset_cause(void)
{
    uint32_t csr = RCC->CSR;
    const char *c = "unknown";
    if (csr & RCC_CSR_IWDGRSTF) c = "iwdg";
    else if (csr & RCC_CSR_WWDGRSTF) c = "wwdg";
    else if (csr & RCC_CSR_LPWRRSTF) c = "lowpower";
    else if (csr & RCC_CSR_SFTRSTF) c = "software";
    else if (csr & RCC_CSR_OBLRSTF) c = "option_bytes";
    else if (csr & RCC_CSR_BORRSTF) c = "power";   /* BOR also sets PINRSTF */
    else if (csr & RCC_CSR_PINRSTF) c = "pin";
    RCC->CSR |= RCC_CSR_RMVF;
    return c;
}

void iwdg_init(void)
{
    /* LSI ~32 kHz / 32 = ~1 kHz, so the reload is in ms. The watchdog and
     * TIM1 stop while a debugger halts the core (TIM1 outputs go idle). */
    DBGMCU->APB1FZR1 |= DBGMCU_APB1FZR1_DBG_IWDG_STOP;
    DBGMCU->APB2FZ |= DBGMCU_APB2FZ_DBG_TIM1_STOP;
    IWDG->KR = 0xCCCCu;
    IWDG->KR = 0x5555u;
    IWDG->PR = 3u;
    IWDG->RLR = IWDG_TIMEOUT_MS > 4095u ? 4095u : IWDG_TIMEOUT_MS;
    for (uint32_t n = 0; IWDG->SR && n < 1000000u; n++) { }
    IWDG->KR = 0xAAAAu;
}

void iwdg_kick(void)
{
    IWDG->KR = 0xAAAAu;
}
