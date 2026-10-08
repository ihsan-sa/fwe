/* clock.c - HSI16 -> PLL -> 170 MHz SYSCLK in range 1 boost mode, SysTick 1 ms.
 * PLL: 16 MHz / M 4 = 4 MHz, x N 85 = 340 MHz VCO, / R 2 = 170 MHz.
 * Boost entry follows RM0440 (reset and clock control, "switching to range 1
 * boost"): AHB /2 first, clear PWR_CR5.R1MODE, 4 flash wait states, switch
 * to the PLL, wait 1 us, then AHB /1. APB1 = APB2 = 170 MHz. */
#include "app.h"

static volatile uint32_t s_ms;

void SysTick_Handler(void)
{
    s_ms++;
}

uint32_t millis(void)
{
    return s_ms;
}

void delay_us(uint32_t us)
{
    /* crude: >= 4 cycles per iteration, so this only ever waits longer */
    volatile uint32_t n = us * (SystemCoreClock / 4000000u + 1u);
    while (n--) { }
}

void clock_init(void)
{
    RCC->APB1ENR1 |= RCC_APB1ENR1_PWREN;
    (void)RCC->APB1ENR1;

    RCC->CR |= RCC_CR_HSION;
    while (!(RCC->CR & RCC_CR_HSIRDY)) { }

    /* AHB /2 while stepping up (1000 = /2) */
    RCC->CFGR = (RCC->CFGR & ~RCC_CFGR_HPRE) | RCC_CFGR_HPRE_3;
    PWR->CR5 &= ~PWR_CR5_R1MODE; /* 0 = range 1 boost */

    FLASH->ACR = (FLASH->ACR & ~FLASH_ACR_LATENCY) | FLASH_ACR_LATENCY_4WS
               | FLASH_ACR_PRFTEN | FLASH_ACR_ICEN | FLASH_ACR_DCEN;
    while ((FLASH->ACR & FLASH_ACR_LATENCY) != FLASH_ACR_LATENCY_4WS) { }

    RCC->CR &= ~RCC_CR_PLLON;
    while (RCC->CR & RCC_CR_PLLRDY) { }
    RCC->PLLCFGR = RCC_PLLCFGR_PLLSRC_1            /* 10 = HSI16 */
                 | (3u << RCC_PLLCFGR_PLLM_Pos)    /* M = 4 */
                 | (85u << RCC_PLLCFGR_PLLN_Pos)   /* N = 85 */
                 | (0u << RCC_PLLCFGR_PLLR_Pos)    /* R = 2 */
                 | RCC_PLLCFGR_PLLREN;
    RCC->CR |= RCC_CR_PLLON;
    while (!(RCC->CR & RCC_CR_PLLRDY)) { }

    RCC->CFGR = (RCC->CFGR & ~(RCC_CFGR_SW | RCC_CFGR_PPRE1 | RCC_CFGR_PPRE2))
              | RCC_CFGR_SW_0 | RCC_CFGR_SW_1;
    while ((RCC->CFGR & RCC_CFGR_SWS) != (RCC_CFGR_SWS_0 | RCC_CFGR_SWS_1)) { }

    for (volatile uint32_t n = 0; n < 200u; n++) { } /* >= 1 us at 85 MHz */
    RCC->CFGR &= ~RCC_CFGR_HPRE;

    SystemCoreClockUpdate();
    SysTick_Config(SystemCoreClock / 1000u);
}

int clock_is_pll_170(void)
{
    return (RCC->CFGR & RCC_CFGR_SWS) == (RCC_CFGR_SWS_0 | RCC_CFGR_SWS_1)
        && SystemCoreClock == 170000000u;
}
