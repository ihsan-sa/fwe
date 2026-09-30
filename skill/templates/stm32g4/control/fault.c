#include "fault.h"

static float absf(float x) { return x < 0.0f ? -x : x; }

uint32_t fault_check(const fault_limits_t *lim, float vbus_v, const float i_a[3])
{
    uint32_t f = 0u;
    if (!(vbus_v < lim->vbus_ov_v)) f |= FAULT_OV; /* NaN trips too */
    if (!(vbus_v > lim->vbus_uv_v)) f |= FAULT_UV;
    for (int k = 0; k < 3; k++) {
        float m = absf(i_a[k]);
        if (!(m < lim->i_trip_a)) f |= FAULT_OC;
        if (!(m < lim->i_limit_a)) f |= FAULT_ILIM;
    }
    return f;
}

void fault_init(fault_state_t *s)
{
    s->latched = 0u;
}

uint32_t fault_latch(fault_state_t *s, uint32_t bits)
{
    uint32_t fresh = bits & ~s->latched;
    s->latched |= bits;
    return fresh;
}

uint32_t fault_update(fault_state_t *s, uint32_t active)
{
    return fault_latch(s, active);
}

uint32_t fault_clear(fault_state_t *s, uint32_t active)
{
    uint32_t blocking = s->latched & active;
    if (blocking) return blocking;
    s->latched = 0u;
    return 0u;
}

int fault_is_latched(const fault_state_t *s)
{
    return s->latched != 0u;
}

const char *fault_name(uint32_t bit)
{
    switch (bit) {
    case FAULT_OV: return "ov";
    case FAULT_UV: return "uv";
    case FAULT_OC: return "oc";
    case FAULT_ILIM: return "ilim";
    case FAULT_OC_HW: return "oc_hw";
    case FAULT_HALL: return "hall";
    default: return "?";
    }
}
