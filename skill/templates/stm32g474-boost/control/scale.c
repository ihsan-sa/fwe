#include <math.h>
#include "scale.h"

float scale_counts_v(uint32_t raw, float vref)
{
    return (float)raw * vref / ADC_FULL;
}

float scale_current_a(float v_pin, float ref_v, float gain, float shunt_ohm)
{
    float vpa = gain * shunt_ohm;
    if (!(vpa > 0.0f))
        return NAN;
    return (v_pin - ref_v) / vpa;
}

float scale_ntc_c(float v_pin, float vdd, float pullup_ohm, float r25_ohm, float beta)
{
    if (!(v_pin > 0.02f * vdd) || !(v_pin < 0.98f * vdd))
        return NAN;
    float r = pullup_ohm * v_pin / (vdd - v_pin);
    return 1.0f / (1.0f / 298.15f + logf(r / r25_ohm) / beta) - 273.15f;
}

uint32_t scale_dac_code(float v_pin, float vref)
{
    float c = v_pin / vref * ADC_FULL + 0.5f;
    if (!(c > 0.0f))
        return 0u;
    return c >= ADC_FULL ? 4095u : (uint32_t)c;
}

uint32_t hr_period(uint32_t fhrtim_hz, uint32_t fsw_hz, uint32_t ckpsc)
{
    uint64_t f = ((uint64_t)fhrtim_hz * 32u) >> ckpsc;
    return (uint32_t)((f + fsw_hz / 2u) / fsw_hz);
}

uint32_t hr_deadtime(uint32_t ns, uint32_t fhrtim_hz, uint32_t dtprsc)
{
    /* counts = ns / tDTG = ns * 8 * fHRTIM / (2^dtprsc * 1e9) */
    uint64_t num = (uint64_t)ns * 8u * fhrtim_hz;
    uint64_t den = (uint64_t)1000000000u << dtprsc;
    uint64_t n = (num + den - 1u) / den;
    return n > HR_DT_MAX ? HR_DT_MAX : (uint32_t)n;
}

uint32_t hr_duty_cmp(float d, float d_max, uint32_t per)
{
    if (!(d > 0.0f))
        return 0u; /* also NaN */
    if (d > d_max)
        d = d_max;
    float c = d * (float)per + 0.5f;
    if (c < (float)HR_CMP_MIN)
        return 0u;
    uint32_t cmp = (uint32_t)c;
    return cmp > per - HR_CMP_MIN ? per - HR_CMP_MIN : cmp;
}

uint32_t hr_adc_cmp(uint32_t cmp1, uint32_t per)
{
    uint32_t c = cmp1 ? cmp1 / 2u : per / 2u;
    return c < HR_CMP_MIN ? HR_CMP_MIN : c;
}
