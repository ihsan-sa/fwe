/* comp.c - the two hardware trips: a comparator per sense pin, its threshold
 * from a DAC channel, its output on an HRTIM fault input (hrtim.c).
 *
 * Routes (RM0440 chapter 24, Tables 199 and 200): INPSEL = 0 puts PA1 on
 * COMP1+ and PA0 on COMP3+. Both comparators can take DAC3_CH1 (INMSEL 100)
 * or DAC1_CH1 (INMSEL 101) on their minus input, so OCP (COMP1) gets
 * DAC3_CH1 and OVP (COMP3) gets DAC1_CH1: two thresholds need two DACs.
 * Both DACs run MODE1 = 011 (on-chip only, buffer off, RM0440 22.7.16), so
 * PA4 is not driven; HFSEL = 10 because AHB runs above 160 MHz.
 *
 * Output: non-inverted, high when the sense pin is over the threshold, which
 * is the active-high level the FLTn inputs expect. COMP_HYST sets the
 * hysteresis (010 = 20 mV). Each CSR is locked after setup, so nothing short
 * of a reset can change a trip. */
#include "app.h"
#include "scale.h"

#if TRIP_OCP_COMP != 1u || TRIP_OVP_COMP != 3u || PIN_ISNS_COMP != 1u || PIN_VOUT_SNS_COMP != 3u
#error "comp.c routes OCP on COMP1 (PA1) and OVP on COMP3 (PA0): check RM0440 Table 200 for another pair"
#endif

#define INMSEL_DAC3_CH1 (4u << COMP_CSR_INMSEL_Pos)
#define INMSEL_DAC1_CH1 (5u << COMP_CSR_INMSEL_Pos)

static float s_ovp_v, s_ocp_v;

static int dac_ch1_init(DAC_TypeDef *d, float v_pin)
{
    d->CR &= ~DAC_CR_EN1;
    d->MCR = (d->MCR & ~(DAC_MCR_MODE1 | DAC_MCR_HFSEL)) | DAC_MCR_MODE1_0 | DAC_MCR_MODE1_1 | DAC_MCR_HFSEL_1;
    d->DHR12R1 = scale_dac_code(v_pin, RAIL_VDDA_V);
    d->CR |= DAC_CR_EN1;
    for (uint32_t n = 0; n < 200000u; n++)
        if (d->SR & DAC_SR_DAC1RDY) return 0;
    return -1;
}

static void comp_setup(COMP_TypeDef *c, uint32_t inmsel)
{
    c->CSR = inmsel | (COMP_HYST << COMP_CSR_HYST_Pos); /* INPSEL = 0, POL = 0, no blanking */
    c->CSR |= COMP_CSR_EN;
}

int comp_init(void)
{
    RCC->APB2ENR |= RCC_APB2ENR_SYSCFGEN;           /* the COMP registers sit in SYSCFG's clock domain */
    RCC->AHB2ENR |= RCC_AHB2ENR_DAC1EN | RCC_AHB2ENR_DAC3EN;
    (void)RCC->AHB2ENR;
    gpio_mode(PIN_ISNS_PORT, PIN_ISNS_PIN, GPIO_ANALOG);
    gpio_mode(PIN_VOUT_SNS_PORT, PIN_VOUT_SNS_PIN, GPIO_ANALOG);

    s_ovp_v = VOUT_OV_V / VOUT_SNS_RATIO;
    s_ocp_v = ISNS_REF_V + I_TRIP_A * ISNS_GAIN * ISNS_SHUNT_OHM;
    int r = 0;
    if (!(s_ovp_v < RAIL_VDDA_V) || !(s_ocp_v < RAIL_VDDA_V)) r = -1; /* a trip the pin can never reach */
    if (dac_ch1_init(DAC3, s_ocp_v) || dac_ch1_init(DAC1, s_ovp_v)) r = -2;

    comp_setup(COMP1, INMSEL_DAC3_CH1);
    comp_setup(COMP3, INMSEL_DAC1_CH1);
    delay_us(20);                                   /* comparator start-up before the first read */
    COMP1->CSR |= COMP_CSR_LOCK;
    COMP3->CSR |= COMP_CSR_LOCK;
    if (r == 0 && comp_active()) r = -3;            /* already over a threshold: refuse to call it armed */
    return r;
}

uint32_t comp_active(void)
{
    uint32_t a = 0u;
    if (COMP3->CSR & COMP_CSR_VALUE) a |= TRIP_OVP_HW;
    if (COMP1->CSR & COMP_CSR_VALUE) a |= TRIP_OCP_HW;
    return a;
}

float comp_threshold_v(uint32_t trip_bit)
{
    return trip_bit == TRIP_OVP_HW ? s_ovp_v : trip_bit == TRIP_OCP_HW ? s_ocp_v : 0.0f;
}
