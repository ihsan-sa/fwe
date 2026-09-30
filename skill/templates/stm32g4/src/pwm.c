/* pwm.c - TIM1 complementary center-aligned PWM for the three half bridges.
 *
 * Safe-state contract (design.md, safety defaults):
 * - pwm_gate_pins_safe() drives every INHx/INLx low as a GPIO output before
 *   anything else runs.
 * - TIM1 comes up with MOE = 0, OISx = OISxN = 0 (idle low) and OSSI = 1, so
 *   while MOE = 0 the timer actively drives all six outputs low; only then
 *   does pwm_gate_pins_af() hand the pins to the timer.
 * - "Gate enable" is MOE: the driver has no enable pin. AOE = 0, so after a
 *   break MOE stays 0 until software arms again.
 * - Duty 0 on a complementary pair means the low side is on: arming at duty 0
 *   clamps all three phases to ground (and charges the bootstrap caps).
 *
 * Hardware over-current trip (HW_TRIP_ENABLE): the three current-sense pins
 * are COMP1/2/4 non-inverting inputs. DAC3 (internal only) sets the trip
 * voltage on its two channels; each comparator's inverting input selects
 * DAC3; the comparator outputs feed the TIM1 break (TIM1_AF1.BKCMPxE), which
 * clears MOE in hardware within a few timer clocks. Positive current only:
 * the negative direction is covered by the software checks in safety.c.
 *
 * Verified against stm32g431xx.h: every register and bit name used here
 * (TIM1->AF1 BKCMPxE, BDTR fields, COMP CSR fields, DAC MCR/SR fields).
 * NOT verified (RM0440 encodings the header does not carry; from memory,
 * check on hardware before trusting the hardware trip):
 *   - COMPx_CSR.INMSEL = 100b selects DAC3 (CH1 for COMP1/3, CH2 for
 *     COMP2/4). Both DAC3 channels get the same code so the CH1/CH2 split
 *     does not matter, but the 100b value itself does.
 *   - COMPx_CSR.INPSEL: 0 = PA1/PA7/PB0 and 1 = PB1/PA3/PE7 for COMP1/2/4.
 *   - DAC_MCR.MODEx = 011b (internal connection, buffer off) and
 *     HFSEL = 10b (AHB above 160 MHz).
 *   - the comparator register interface needing only SYSCFGEN.
 * pwm_hw_trip_init() checks the one thing it can: with the bridge off every
 * comparator output must read low. A wrong INMSEL that picks a low reference
 * fails that check and arming is refused; one that picks a floating pin
 * could pass it and leave only the software limit. The `selftest` reports
 * the result as "hw_trip". */
#include "app.h"
#include "pwm_math.h"

typedef struct { GPIO_TypeDef *port; uint32_t pin, af; } gate_pin_t;

static const gate_pin_t k_gate[6] = {
    { PIN_INHA_PORT, PIN_INHA_PIN, PIN_INHA_AF },
    { PIN_INHB_PORT, PIN_INHB_PIN, PIN_INHB_AF },
    { PIN_INHC_PORT, PIN_INHC_PIN, PIN_INHC_AF },
    { PIN_INLA_PORT, PIN_INLA_PIN, PIN_INLA_AF },
    { PIN_INLB_PORT, PIN_INLB_PIN, PIN_INLB_AF },
    { PIN_INLC_PORT, PIN_INLC_PIN, PIN_INLC_AF },
};

static uint32_t s_arr;

void pwm_gate_pins_safe(void)
{
    for (int k = 0; k < 6; k++) {
        gpio_write(k_gate[k].port, k_gate[k].pin, 0);            /* ODR low first */
        k_gate[k].port->OTYPER &= ~(1u << k_gate[k].pin);         /* push-pull */
        k_gate[k].port->PUPDR &= ~(3u << (k_gate[k].pin * 2u));
        k_gate[k].port->OSPEEDR |= 2u << (k_gate[k].pin * 2u);   /* high speed */
        gpio_mode(k_gate[k].port, k_gate[k].pin, GPIO_OUT);
    }
}

void pwm_init(void)
{
    RCC->APB2ENR |= RCC_APB2ENR_TIM1EN | RCC_APB2ENR_SYSCFGEN;
    (void)RCC->APB2ENR;

    uint32_t f_tim = SystemCoreClock; /* APB2 /1 -> TIM1 kernel = SYSCLK */
    s_arr = pwm_arr_center(f_tim, PWM_FREQ_HZ);
    uint8_t dtg = pwm_dtg_encode(pwm_deadtime_ticks(DEADTIME_NS, f_tim));

    TIM1->CR1 = 0u;
    TIM1->CR1 = TIM_CR1_CMS_0 | TIM_CR1_ARPE;  /* center-aligned mode 1, CKD = 0 */
    TIM1->CR2 = 0u;                             /* OISx = OISxN = 0: idle low */
    TIM1->PSC = 0u;
    TIM1->ARR = s_arr;
    TIM1->RCR = 0u;
    TIM1->CCR1 = TIM1->CCR2 = TIM1->CCR3 = 0u;
    TIM1->CCMR1 = TIM_CCMR1_OC1M_1 | TIM_CCMR1_OC1M_2 | TIM_CCMR1_OC1PE   /* PWM mode 1 */
                | TIM_CCMR1_OC2M_1 | TIM_CCMR1_OC2M_2 | TIM_CCMR1_OC2PE;
    TIM1->CCMR2 = TIM_CCMR2_OC3M_1 | TIM_CCMR2_OC3M_2 | TIM_CCMR2_OC3PE;
    TIM1->CCER = TIM_CCER_CC1E | TIM_CCER_CC1NE | TIM_CCER_CC2E | TIM_CCER_CC2NE
               | TIM_CCER_CC3E | TIM_CCER_CC3NE;                      /* all active high */
    TIM1->AF1 = 0u;   /* reset value has BKINE = 1; the BKIN pin is not ours */
    TIM1->AF2 = 0u;
    TIM1->BDTR = ((uint32_t)dtg << TIM_BDTR_DTG_Pos) | TIM_BDTR_OSSR | TIM_BDTR_OSSI;
    TIM1->EGR = TIM_EGR_UG;
    TIM1->SR = 0u;
    TIM1->CR1 |= TIM_CR1_CEN;
}

void pwm_gate_pins_af(void)
{
    for (int k = 0; k < 6; k++) {
        gpio_af(k_gate[k].port, k_gate[k].pin, k_gate[k].af);
        gpio_mode(k_gate[k].port, k_gate[k].pin, GPIO_AF);
    }
}

#if HW_TRIP_ENABLE
typedef struct { uint32_t n; GPIO_TypeDef *port; uint32_t pin; } trip_in_t;

static const trip_in_t k_trip[3] = {
    { PIN_ISENSE_A_COMP, PIN_ISENSE_A_PORT, PIN_ISENSE_A_PIN },
    { PIN_ISENSE_B_COMP, PIN_ISENSE_B_PORT, PIN_ISENSE_B_PIN },
    { PIN_ISENSE_C_COMP, PIN_ISENSE_C_PORT, PIN_ISENSE_C_PIN },
};

static COMP_TypeDef *comp_of(uint32_t n)
{
    switch (n) {
    case 1u: return COMP1;
    case 2u: return COMP2;
    case 3u: return COMP3;
    case 4u: return COMP4;
    default: return 0;
    }
}

/* INPSEL for a pin on COMPn's non-inverting input, or -1 if unknown (RM0440, unverified). */
static int comp_inpsel(uint32_t n, GPIO_TypeDef *port, uint32_t pin)
{
    if (n == 1u) return port == GPIOA && pin == 1u ? 0 : port == GPIOB && pin == 1u ? 1 : -1;
    if (n == 2u) return port == GPIOA && pin == 7u ? 0 : port == GPIOA && pin == 3u ? 1 : -1;
    if (n == 3u) return port == GPIOA && pin == 0u ? 0 : port == GPIOC && pin == 1u ? 1 : -1;
    if (n == 4u) return port == GPIOB && pin == 0u ? 0 : port == GPIOE && pin == 7u ? 1 : -1;
    return -1;
}

static uint32_t s_trip_mask; /* COMPn in use, bit n */

int pwm_hw_trip_init(float v_trip)
{
    uint32_t bk = 0u;
    s_trip_mask = 0u;

    float code_f = v_trip / RAIL_VDDA_V * 4095.0f;
    uint32_t code = code_f >= 4095.0f ? 4095u : code_f <= 0.0f ? 0u : (uint32_t)code_f;

    RCC->AHB2ENR |= RCC_AHB2ENR_DAC3EN;
    (void)RCC->AHB2ENR;
    DAC3->CR = 0u;
    DAC3->MCR = (3u << DAC_MCR_MODE1_Pos) | (3u << DAC_MCR_MODE2_Pos) | DAC_MCR_HFSEL_1;
    DAC3->DHR12R1 = code;
    DAC3->DHR12R2 = code;
    DAC3->CR = DAC_CR_EN1 | DAC_CR_EN2;
    uint32_t n = 0;
    while ((DAC3->SR & (DAC_SR_DAC1RDY | DAC_SR_DAC2RDY)) != (DAC_SR_DAC1RDY | DAC_SR_DAC2RDY)) {
        if (++n > 100000u) return -1;
    }

    for (int k = 0; k < 3; k++) {
        COMP_TypeDef *c = comp_of(k_trip[k].n);
        int inp = comp_inpsel(k_trip[k].n, k_trip[k].port, k_trip[k].pin);
        if (!c || inp < 0) return -2;
        c->CSR = (4u << COMP_CSR_INMSEL_Pos)               /* 100b: DAC3 (unverified) */
               | ((uint32_t)inp << COMP_CSR_INPSEL_Pos)
               | (2u << COMP_CSR_HYST_Pos)                  /* small hysteresis */
               | COMP_CSR_EN;                               /* POLARITY 0, no blanking */
        s_trip_mask |= 1u << k_trip[k].n;
        bk |= TIM1_AF1_BKCMP1E << (k_trip[k].n - 1u);
    }
    delay_us(20);
    if (pwm_hw_trip_active()) return -3; /* high at zero current: wrong threshold or input */

    TIM1->AF1 = bk;                       /* BKCMPxP = 0: not inverted; BKINE = 0 */
    TIM1->SR = ~TIM_SR_BIF;
    TIM1->BDTR |= TIM_BDTR_BKE | TIM_BDTR_BKP | (2u << TIM_BDTR_BKF_Pos); /* active high, 4-sample filter */
    delay_us(2);
    TIM1->SR = ~TIM_SR_BIF;
    return 0;
}

int pwm_hw_trip_active(void)
{
    for (uint32_t n = 1u; n <= 4u; n++)
        if ((s_trip_mask & (1u << n)) && (comp_of(n)->CSR & COMP_CSR_VALUE)) return 1;
    return 0;
}
#else
/* TODO: hardware trip disabled in fw_config.h: software over-current only. */
int pwm_hw_trip_init(float v_trip)
{
    (void)v_trip;
    return -4;
}

int pwm_hw_trip_active(void)
{
    return 0;
}
#endif

int pwm_break_flag(void)
{
    return (TIM1->SR & TIM_SR_BIF) != 0u;
}

void pwm_break_flag_clear(void)
{
    TIM1->SR = ~TIM_SR_BIF;
}

void pwm_disarm(void)
{
    TIM1->BDTR &= ~TIM_BDTR_MOE;
    TIM1->CCR1 = TIM1->CCR2 = TIM1->CCR3 = 0u;
    g_app.armed = 0;
    g_app.duty[0] = g_app.duty[1] = g_app.duty[2] = 0.0f;
}

int pwm_arm(void)
{
    TIM1->CCR1 = TIM1->CCR2 = TIM1->CCR3 = 0u;
    TIM1->EGR = TIM_EGR_UG; /* load the zero duty now, not at the next update */
    g_app.duty[0] = g_app.duty[1] = g_app.duty[2] = 0.0f;
    TIM1->BDTR |= TIM_BDTR_MOE;
    if (!(TIM1->BDTR & TIM_BDTR_MOE)) { /* an active break holds MOE at 0 */
        g_app.armed = 0;
        return -1;
    }
    g_app.armed = 1;
    return 0;
}

int pwm_is_armed(void)
{
    return (TIM1->BDTR & TIM_BDTR_MOE) != 0u;
}

void pwm_set_duty(const float d[3])
{
    TIM1->CCR1 = pwm_duty_to_ccr(d[0], MAX_DUTY, s_arr);
    TIM1->CCR2 = pwm_duty_to_ccr(d[1], MAX_DUTY, s_arr);
    TIM1->CCR3 = pwm_duty_to_ccr(d[2], MAX_DUTY, s_arr);
    for (int k = 0; k < 3; k++)
        g_app.duty[k] = (float)pwm_duty_to_ccr(d[k], MAX_DUTY, s_arr) / (float)s_arr;
}
