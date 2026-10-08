#include "trip.h"

static const char *const NAMES[TRIP_COUNT] = {
    "ovp_hw", "ocp_hw", "ov", "oc", "vin_uv", "vin_ov", "ot"
};

uint32_t trip_check(const trip_limits_t *lim, float vout_v, float il_a, float vin_v, float t_c)
{
    uint32_t a = 0;
    /* written as !(x < limit) so a NaN reading trips */
    if (!(vout_v < lim->vout_ov_v)) a |= TRIP_OV;
    if (!(il_a < lim->i_oc_a)) a |= TRIP_OC;
    if (!(vin_v > lim->vin_uv_v)) a |= TRIP_VIN_UV;
    if (!(vin_v < lim->vin_ov_v)) a |= TRIP_VIN_OV;
    if (!(t_c < lim->t_ot_c)) a |= TRIP_OT;
    return a;
}

void trip_init(trip_state_t *s)
{
    s->latched = 0;
}

uint32_t trip_latch(trip_state_t *s, uint32_t bits)
{
    uint32_t fresh = bits & ~s->latched;
    s->latched |= bits;
    return fresh;
}

uint32_t trip_clear(trip_state_t *s, uint32_t active)
{
    uint32_t blocking = s->latched & active;
    if (!blocking)
        s->latched = 0;
    return blocking;
}

int trip_is_latched(const trip_state_t *s)
{
    return s->latched != 0;
}

const char *trip_name(uint32_t bit)
{
    for (unsigned i = 0; i < TRIP_COUNT; i++)
        if (bit == (1u << i))
            return NAMES[i];
    return "?";
}
