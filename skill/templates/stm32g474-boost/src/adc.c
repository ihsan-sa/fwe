/* adc.c - ADC1 injected sequence ISNS, VOUT, VIN, NTC, started by the HRTIM.
 *
 * Bring-up per RM0440 21.4: leave deep power-down, enable the regulator,
 * wait tADCVREG_STUP (20 us), single-ended calibration, then ADEN and wait
 * ADRDY. ADC clock: synchronous HCLK/4 = 42.5 MHz (CKMODE = 11).
 *
 * Trigger: JEXTSEL = 10011 is hrtim_adc_trg2 (Table 167), rising edge.
 * hrtim.c fires it from Timer A CMP2 at mid on-time, once every CTRL_DIV
 * periods, so the JEOS interrupt is the control loop (100 kHz at 1 MHz/10).
 * Sequence time at 42.5 MHz: ISNS 24.5 + 12.5, the three others 47.5 + 12.5
 * cycles each = 217 cycles = 5.1 us, inside the 10 us loop period. */
#include <math.h>
#include "app.h"
#include "scale.h"

/* ADC_CR bits with "rs" access: never write them back as 1 by accident */
#define ADC_CR_RS (ADC_CR_ADCAL | ADC_CR_JADSTP | ADC_CR_ADSTP | ADC_CR_JADSTART \
                   | ADC_CR_ADSTART | ADC_CR_ADDIS | ADC_CR_ADEN)
#define SMP_24  3u        /* 24.5 cycles: the ISNS amplifier output is low impedance */
#define SMP_47  4u        /* 47.5 cycles: the dividers */
#define JEXTSEL_HRTIM_TRG2 19u
#define NTC_EVERY 64u     /* temperature moves slowly: logf once per 64 samples */

#if PIN_ISNS_ADC != 1u || PIN_VOUT_SNS_ADC != 1u || PIN_VIN_SNS_ADC != 1u || PIN_NTC_SNS_ADC != 1u
#error "adc.c samples all four inputs on ADC1"
#endif

typedef struct { uint32_t ch, smp; GPIO_TypeDef *port; uint32_t pin; } ain_t;

/* in JSQ1..4 order, which is g_app.raw[] order */
static const ain_t k_in[4] = {
    { PIN_ISNS_ADC_CH, SMP_24, PIN_ISNS_PORT, PIN_ISNS_PIN },
    { PIN_VOUT_SNS_ADC_CH, SMP_47, PIN_VOUT_SNS_PORT, PIN_VOUT_SNS_PIN },
    { PIN_VIN_SNS_ADC_CH, SMP_47, PIN_VIN_SNS_PORT, PIN_VIN_SNS_PIN },
    { PIN_NTC_SNS_ADC_CH, SMP_47, PIN_NTC_SNS_PORT, PIN_NTC_SNS_PIN },
};

static void cr_set(ADC_TypeDef *a, uint32_t bits)
{
    a->CR = (a->CR & ~ADC_CR_RS) | bits;
}

static int wait_bits(volatile uint32_t *reg, uint32_t mask, uint32_t want)
{
    for (uint32_t n = 0; n < 200000u; n++)
        if ((*reg & mask) == want) return 0;
    return -1;
}

static int adc_bringup(ADC_TypeDef *a)
{
    a->CR = 0u;                    /* DEEPPWD = 0 */
    a->CR = ADC_CR_ADVREGEN;
    delay_us(20);
    a->CR = ADC_CR_ADVREGEN | ADC_CR_ADCAL; /* ADCALDIF = 0: single-ended */
    if (wait_bits(&a->CR, ADC_CR_ADCAL, 0u)) return -1;
    delay_us(1);                   /* >= 4 ADC clocks before ADEN */
    a->ISR = ADC_ISR_ADRDY;
    cr_set(a, ADC_CR_ADEN);
    if (wait_bits(&a->ISR, ADC_ISR_ADRDY, ADC_ISR_ADRDY)) return -2;
    return 0;
}

static void set_sample_time(ADC_TypeDef *a, const ain_t *in)
{
    if (in->ch < 10u)
        a->SMPR1 = (a->SMPR1 & ~(7u << (in->ch * 3u))) | (in->smp << (in->ch * 3u));
    else
        a->SMPR2 = (a->SMPR2 & ~(7u << ((in->ch - 10u) * 3u))) | (in->smp << ((in->ch - 10u) * 3u));
    gpio_mode(in->port, in->pin, GPIO_ANALOG);
}

int adc_init(void)
{
    RCC->AHB2ENR |= RCC_AHB2ENR_ADC12EN;
    (void)RCC->AHB2ENR;
    ADC12_COMMON->CCR = (ADC12_COMMON->CCR & ~ADC_CCR_CKMODE) | ADC_CCR_CKMODE_0 | ADC_CCR_CKMODE_1;
    g_app.temp_c = NAN;            /* no reading yet: the OT check stays active */
    if (adc_bringup(ADC1)) { g_app.adc_ok = 0; return -1; }
    for (int k = 0; k < 4; k++) set_sample_time(ADC1, &k_in[k]);

    /* JL = 3 (four conversions), hardware trigger on the rising edge; the
     * queue is off (JQDIS reset value 1), so JSQR is simply the sequence */
    ADC1->JSQR = (3u << ADC_JSQR_JL_Pos) | (JEXTSEL_HRTIM_TRG2 << ADC_JSQR_JEXTSEL_Pos) | ADC_JSQR_JEXTEN_0
               | (k_in[0].ch << ADC_JSQR_JSQ1_Pos) | (k_in[1].ch << ADC_JSQR_JSQ2_Pos)
               | (k_in[2].ch << ADC_JSQR_JSQ3_Pos) | (k_in[3].ch << ADC_JSQR_JSQ4_Pos);
    ADC1->ISR = ADC_ISR_JEOC | ADC_ISR_JEOS;
    ADC1->IER = ADC_IER_JEOSIE;
    NVIC_SetPriority(ADC1_2_IRQn, 0u); /* the control loop outranks everything */
    NVIC_EnableIRQ(ADC1_2_IRQn);
    cr_set(ADC1, ADC_CR_JADSTART);     /* armed: converts on each HRTIM trigger */
    g_app.adc_ok = 1;
    return 0;
}

void adc_convert(void)
{
    float vdda = RAIL_VDDA_V;
    g_app.il_a = scale_current_a(scale_counts_v(g_app.raw[0], vdda), ISNS_REF_V, ISNS_GAIN, ISNS_SHUNT_OHM);
    g_app.vout_v = scale_counts_v(g_app.raw[1], vdda) * VOUT_SNS_RATIO;
    g_app.vin_v = scale_counts_v(g_app.raw[2], vdda) * VIN_SNS_RATIO;
    if (g_app.samples % NTC_EVERY == 0u)
        g_app.temp_c = scale_ntc_c(scale_counts_v(g_app.raw[3], vdda), vdda,
                                   NTC_SNS_PULLUP_OHM, NTC_SNS_R25_OHM, NTC_SNS_BETA);
}

void ADC1_2_IRQHandler(void)
{
    if (!(ADC1->ISR & ADC_ISR_JEOS)) return;
    g_app.raw[0] = (uint16_t)ADC1->JDR1;
    g_app.raw[1] = (uint16_t)ADC1->JDR2;
    g_app.raw[2] = (uint16_t)ADC1->JDR3;
    g_app.raw[3] = (uint16_t)ADC1->JDR4;
    ADC1->ISR = ADC_ISR_JEOC | ADC_ISR_JEOS;
    safety_sample();
}
