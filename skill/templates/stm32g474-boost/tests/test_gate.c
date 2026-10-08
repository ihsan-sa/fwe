/* test_gate.c - zero duty, disarm and every fault turn BOTH gates off; the
 * outputs come on only once a real pulse has reached the active compare. */
#include "check.h"
#include "gate.h"
#include "scale.h"

#define PER 5440u
#define DMAX 0.82f

/* drive a gate from off to switching at a real duty */
static void to_pwm(gate_t *g)
{
    uint32_t c = hr_duty_cmp(0.5f, DMAX, PER);
    gate_init(g);
    (void)gate_update(g, 1, 0, c, 0);
    (void)gate_update(g, 1, 0, c, 1);
}

int main(void)
{
    gate_t g;
    uint32_t half = hr_duty_cmp(0.5f, DMAX, PER);
    CHECK(half != 0u);

    /* reset state: off */
    gate_init(&g);
    CHECK(!gate_outputs_wanted(&g));

    /* "duty 0" while armed: null compare, so both outputs disabled, never
     * the complement (high side) held on */
    CHECK_EQ(gate_update(&g, 1, 0, hr_duty_cmp(0.0f, DMAX, PER), 1), GATE_ACT_DISABLE);
    CHECK(!gate_outputs_wanted(&g));
    /* a NaN duty, a negative one and a pulse under HR_CMP_MIN are null too */
    CHECK_EQ(gate_update(&g, 1, 0, hr_duty_cmp(0.0f / 0.0f, DMAX, PER), 1), GATE_ACT_DISABLE);
    CHECK_EQ(gate_update(&g, 1, 0, hr_duty_cmp(-0.2f, DMAX, PER), 1), GATE_ACT_DISABLE);
    CHECK_EQ(gate_update(&g, 1, 0, hr_duty_cmp(0.01f, DMAX, PER), 1), GATE_ACT_DISABLE);
    CHECK(!gate_outputs_wanted(&g));

    /* a real duty: held off while CMP1 loads, even if the flag says the
     * previous (null) compare was loaded, then on once */
    CHECK_EQ(gate_update(&g, 1, 0, half, 1), GATE_ACT_NONE);
    CHECK(!gate_outputs_wanted(&g));
    CHECK_EQ(gate_update(&g, 1, 0, half, 1), GATE_ACT_ENABLE);
    CHECK(gate_outputs_wanted(&g));
    CHECK_EQ(gate_update(&g, 1, 0, half + 100u, 0), GATE_ACT_NONE);
    CHECK(gate_outputs_wanted(&g));

    /* pending stays pending until a repetition event has loaded the pulse:
     * a second sample inside the same period must not enable */
    gate_init(&g);
    CHECK_EQ(gate_update(&g, 1, 0, half, 0), GATE_ACT_NONE);
    CHECK_EQ(gate_update(&g, 1, 0, half, 0), GATE_ACT_NONE);
    CHECK_EQ(gate_update(&g, 1, 0, half, 0), GATE_ACT_NONE);
    CHECK(!gate_outputs_wanted(&g));
    CHECK_EQ(gate_update(&g, 1, 0, half, 1), GATE_ACT_ENABLE);

    /* switching, then duty 0: both off at once, loaded or not */
    to_pwm(&g);
    CHECK(gate_outputs_wanted(&g));
    CHECK_EQ(gate_update(&g, 1, 0, 0u, 0), GATE_ACT_DISABLE);
    CHECK(!gate_outputs_wanted(&g));
    /* and back up: through pending again, never straight on */
    CHECK_EQ(gate_update(&g, 1, 0, half, 1), GATE_ACT_NONE);
    CHECK_EQ(gate_update(&g, 1, 0, half, 1), GATE_ACT_ENABLE);

    /* switching, then disarm (compare still non-zero): both off */
    to_pwm(&g);
    CHECK_EQ(gate_update(&g, 0, 0, half, 1), GATE_ACT_DISABLE);
    CHECK(!gate_outputs_wanted(&g));
    /* disarmed, a later duty write does not switch anything on */
    CHECK_EQ(gate_update(&g, 0, 0, half, 1), GATE_ACT_DISABLE);
    CHECK(!gate_outputs_wanted(&g));

    /* switching, then a fault: both off, and they stay off while it lasts */
    to_pwm(&g);
    CHECK_EQ(gate_update(&g, 1, 1, half, 1), GATE_ACT_DISABLE);
    CHECK(!gate_outputs_wanted(&g));
    CHECK_EQ(gate_update(&g, 1, 1, half, 1), GATE_ACT_DISABLE);
    CHECK(!gate_outputs_wanted(&g));
    /* a fault with a null duty is still off */
    CHECK_EQ(gate_update(&g, 1, 1, 0u, 1), GATE_ACT_DISABLE);

    /* pending, then disarm or fault before the enable: never enables */
    gate_init(&g);
    CHECK_EQ(gate_update(&g, 1, 0, half, 0), GATE_ACT_NONE);
    CHECK_EQ(gate_update(&g, 0, 0, half, 1), GATE_ACT_DISABLE);
    CHECK_EQ(gate_update(&g, 1, 0, half, 1), GATE_ACT_NONE);
    CHECK_EQ(gate_update(&g, 1, 1, half, 1), GATE_ACT_DISABLE);
    CHECK(!gate_outputs_wanted(&g));

    /* the largest duty is a real pulse and switches */
    gate_init(&g);
    uint32_t top = hr_duty_cmp(1.0f, DMAX, PER);
    CHECK(top != 0u);
    CHECK_EQ(gate_update(&g, 1, 0, top, 0), GATE_ACT_NONE);
    CHECK_EQ(gate_update(&g, 1, 0, top, 1), GATE_ACT_ENABLE);
    CHECK_DONE();
}
