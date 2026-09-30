/* adc.c - software-triggered single conversions of VBUS and the three phase
 * currents on the ADC instances gen/board_pins.h names.
 * Bring-up per RM0440: leave deep power-down, enable the regulator, wait
 * tADCVREG_STUP (20 us), single-ended calibration, then ADEN and wait ADRDY.
 * ADC clock: synchronous HCLK/4 = 42.5 MHz (CKMODE = 11). */
#include "app.h"
#include "sense.h"

/* ADC_CR bits with "rs" access: never write them back as 1 by accident */
#define ADC_CR_RS (ADC_CR_ADCAL | ADC_CR_JADSTP | ADC_CR_ADSTP | ADC_CR_JADSTART \
                   | ADC_CR_ADSTART | ADC_CR_ADDIS | ADC_CR_ADEN)
#define SMP_247 6u /* 247.5 cycles: the VBUS divider is ~9 kOhm */

typedef struct { uint32_t adc, ch; GPIO_TypeDef *port; uint32_t pin; } ain_t;

static const ain_t k_vbus = { PIN_VBUS_SENSE_ADC, PIN_VBUS_SENSE_ADC_CH, PIN_VBUS_SENSE_PORT, PIN_VBUS_SENSE_PIN };
static const ain_t k_isense[3] = {
    { PIN_ISENSE_A_ADC, PIN_ISENSE_A_ADC_CH, PIN_ISENSE_A_PORT, PIN_ISENSE_A_PIN },
    { PIN_ISENSE_B_ADC, PIN_ISENSE_B_ADC_CH, PIN_ISENSE_B_PORT, PIN_ISENSE_B_PIN },
    { PIN_ISENSE_C_ADC, PIN_ISENSE_C_ADC_CH, PIN_ISENSE_C_PORT, PIN_ISENSE_C_PIN },
};
static const float k_gain[3] = { ISENSE_A_GAIN, ISENSE_B_GAIN, ISENSE_C_GAIN };
static const float k_shunt[3] = { ISENSE_A_SHUNT_OHM, ISENSE_B_SHUNT_OHM, ISENSE_C_SHUNT_OHM };
static const float k_ref[3] = { ISENSE_A_REF_V, ISENSE_B_REF_V, ISENSE_C_REF_V };

static ADC_TypeDef *adc_of(uint32_t n)
{
    return n == 2u ? ADC2 : ADC1;
}

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
    a->CFGR = (a->CFGR & ~(ADC_CFGR_CONT | ADC_CFGR_DISCEN)) | ADC_CFGR_OVRMOD;
    return 0;
}

static void set_sample_time(const ain_t *in)
{
    ADC_TypeDef *a = adc_of(in->adc);
    if (in->ch < 10u)
        a->SMPR1 = (a->SMPR1 & ~(7u << (in->ch * 3u))) | (SMP_247 << (in->ch * 3u));
    else
        a->SMPR2 = (a->SMPR2 & ~(7u << ((in->ch - 10u) * 3u))) | (SMP_247 << ((in->ch - 10u) * 3u));
    gpio_mode(in->port, in->pin, GPIO_ANALOG);
}

static int adc_read(const ain_t *in, uint16_t *out)
{
    ADC_TypeDef *a = adc_of(in->adc);
    a->SQR1 = in->ch << ADC_SQR1_SQ1_Pos; /* L = 0: one conversion */
    a->ISR = ADC_ISR_EOC | ADC_ISR_EOS;
    cr_set(a, ADC_CR_ADSTART);
    if (wait_bits(&a->ISR, ADC_ISR_EOC, ADC_ISR_EOC)) return -1;
    *out = (uint16_t)a->DR;
    return 0;
}

int adc_init(void)
{
    RCC->AHB2ENR |= RCC_AHB2ENR_ADC12EN;
    (void)RCC->AHB2ENR;
    ADC12_COMMON->CCR = (ADC12_COMMON->CCR & ~ADC_CCR_CKMODE) | ADC_CCR_CKMODE_0 | ADC_CCR_CKMODE_1;
    int ok = adc_bringup(ADC1) == 0 && adc_bringup(ADC2) == 0;
    set_sample_time(&k_vbus);
    for (int k = 0; k < 3; k++) {
        set_sample_time(&k_isense[k]);
        g_app.i_ref_v[k] = k_ref[k];
    }
    g_app.adc_ok = ok;
    return ok ? 0 : -1;
}

void adc_sample(void)
{
    int ok = adc_read(&k_vbus, &g_app.raw_vbus) == 0;
    g_app.vbus_v = sense_vbus_v(sense_counts_to_v(g_app.raw_vbus, RAIL_VDDA_V), VBUS_SENSE_RATIO);
    for (int k = 0; k < 3; k++) {
        ok &= adc_read(&k_isense[k], &g_app.raw_i[k]) == 0;
        g_app.i_a[k] = sense_current_a(sense_counts_to_v(g_app.raw_i[k], RAIL_VDDA_V),
                                       g_app.i_ref_v[k], k_gain[k], k_shunt[k]);
    }
    g_app.adc_ok = ok;
}

/* Bridge must be off: the true current is zero, so the mean is the offset.
 * An offset too far from the nominal REF keeps the nominal and fails. */
int adc_calibrate_offsets(void)
{
    sense_avg_t avg[3];
    for (int k = 0; k < 3; k++) sense_avg_reset(&avg[k]);
    for (uint32_t s = 0; s < OFFSET_SAMPLES; s++) {
        for (int k = 0; k < 3; k++) {
            uint16_t raw;
            if (adc_read(&k_isense[k], &raw)) return -1;
            sense_avg_add(&avg[k], sense_counts_to_v(raw, RAIL_VDDA_V));
        }
    }
    int ok = 1;
    for (int k = 0; k < 3; k++) {
        float m = sense_avg_mean(&avg[k], k_ref[k]);
        if (sense_offset_ok(m, k_ref[k], OFFSET_TOL_V)) {
            g_app.i_ref_v[k] = m;
        } else {
            g_app.i_ref_v[k] = k_ref[k];
            ok = 0;
        }
    }
    g_app.offsets_ok = ok;
    return ok ? 0 : -2;
}
