/* board.c - GPIO helpers, reset cause and the watchdog. */
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

void board_gpio_clocks(void)
{
    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN | RCC_AHB2ENR_GPIOBEN | RCC_AHB2ENR_GPIOCEN
                  | RCC_AHB2ENR_GPIODEN | RCC_AHB2ENR_GPIOEEN | RCC_AHB2ENR_GPIOFEN
                  | RCC_AHB2ENR_GPIOGEN;
    (void)RCC->AHB2ENR;
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
     * HRTIM (hrtim.c) stop while a debugger halts the core. */
    DBGMCU->APB1FZR1 |= DBGMCU_APB1FZR1_DBG_IWDG_STOP;
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
