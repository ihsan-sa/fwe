#include "pwm_math.h"

uint32_t pwm_arr_center(uint32_t f_tim_hz, uint32_t f_pwm_hz)
{
    return f_pwm_hz ? f_tim_hz / (2u * f_pwm_hz) : 0u;
}

uint32_t pwm_deadtime_ticks(uint32_t ns, uint32_t f_tim_hz)
{
    uint64_t t = (uint64_t)ns * f_tim_hz;
    return (uint32_t)((t + 999999999u) / 1000000000u);
}

uint32_t pwm_dtg_ticks(uint8_t dtg)
{
    if ((dtg & 0x80u) == 0u) return dtg;
    if ((dtg & 0xC0u) == 0x80u) return (64u + (dtg & 0x3Fu)) * 2u;
    if ((dtg & 0xE0u) == 0xC0u) return (32u + (dtg & 0x1Fu)) * 8u;
    return (32u + (dtg & 0x1Fu)) * 16u;
}

uint8_t pwm_dtg_encode(uint32_t ticks)
{
    if (ticks <= 127u) return (uint8_t)ticks;
    if (ticks <= 254u) return (uint8_t)(0x80u | ((ticks + 1u) / 2u - 64u));
    if (ticks <= 504u) return (uint8_t)(0xC0u | ((ticks + 7u) / 8u - 32u));
    if (ticks <= 1008u) return (uint8_t)(0xE0u | ((ticks + 15u) / 16u - 32u));
    return 0xFFu;
}

uint32_t pwm_duty_to_ccr(float duty, float max_duty, uint32_t arr)
{
    if (!(duty > 0.0f)) return 0u;
    if (duty > max_duty) duty = max_duty;
    if (duty > 1.0f) duty = 1.0f;
    return (uint32_t)(duty * (float)arr + 0.5f);
}
