#include "softstart.h"

void ss_start(softstart_t *s, float vin_v, float target_v, float slew_v_per_s)
{
    s->ref_v = vin_v < target_v ? vin_v : target_v;
    s->target_v = target_v;
    s->slew_v_per_s = slew_v_per_s;
    s->done = s->ref_v >= target_v;
}

float ss_step(softstart_t *s, float dt)
{
    if (!s->done) {
        s->ref_v += s->slew_v_per_s * dt;
        if (s->ref_v >= s->target_v) {
            s->ref_v = s->target_v;
            s->done = 1;
        }
    }
    return s->ref_v;
}
