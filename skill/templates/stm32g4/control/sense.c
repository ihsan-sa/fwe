#include "sense.h"

float sense_counts_to_v(uint32_t counts, float vref)
{
    return (float)counts * vref / SENSE_ADC_FULL_SCALE;
}

float sense_current_a(float v, float ref_v, float gain, float shunt_ohm)
{
    float k = gain * shunt_ohm;
    return k > 0.0f ? (v - ref_v) / k : 0.0f;
}

float sense_current_to_v(float i_a, float ref_v, float gain, float shunt_ohm)
{
    return ref_v + i_a * gain * shunt_ohm;
}

float sense_vbus_v(float v_pin, float ratio)
{
    return v_pin * ratio;
}

void sense_avg_reset(sense_avg_t *a)
{
    a->sum = 0.0f;
    a->n = 0u;
}

void sense_avg_add(sense_avg_t *a, float x)
{
    a->sum += x;
    a->n++;
}

float sense_avg_mean(const sense_avg_t *a, float fallback)
{
    return a->n ? a->sum / (float)a->n : fallback;
}

int sense_offset_ok(float measured_v, float nominal_v, float tol_v)
{
    float e = measured_v - nominal_v;
    return e <= tol_v && e >= -tol_v;
}
