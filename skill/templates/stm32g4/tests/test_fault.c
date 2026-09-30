#include "check.h"
#include "fault.h"

int main(void)
{
    const fault_limits_t lim = { 30.0f, 9.0f, 20.0f, 15.0f };
    const float i0[3] = { 0.0f, 0.5f, -0.5f };
    const float i16[3] = { 0.0f, -16.0f, 0.0f };
    const float i21[3] = { 21.0f, 0.0f, 0.0f };
    fault_state_t s;
    fault_init(&s);

    CHECK_EQ(fault_check(&lim, 24.0f, i0), 0);
    CHECK_EQ(fault_check(&lim, 30.0f, i0), FAULT_OV);
    CHECK_EQ(fault_check(&lim, 9.0f, i0), FAULT_UV);
    CHECK_EQ(fault_check(&lim, 24.0f, i16), FAULT_ILIM);
    CHECK_EQ(fault_check(&lim, 24.0f, i21), FAULT_ILIM | FAULT_OC);
    CHECK_EQ(fault_check(&lim, 0.0f / 0.0f, i0), FAULT_OV | FAULT_UV); /* NaN trips */

    /* nothing active: nothing latched */
    CHECK_EQ(fault_update(&s, fault_check(&lim, 24.0f, i0)), 0);
    CHECK(!fault_is_latched(&s));

    /* trip: OV latches, reported once as new */
    CHECK_EQ(fault_update(&s, fault_check(&lim, 31.0f, i0)), FAULT_OV);
    CHECK_EQ(fault_update(&s, fault_check(&lim, 31.0f, i0)), 0);
    CHECK(fault_is_latched(&s));
    /* persists after the condition goes away */
    fault_update(&s, fault_check(&lim, 24.0f, i0));
    CHECK_EQ(s.latched, FAULT_OV);

    /* clear refused while the condition persists, latch untouched */
    fault_update(&s, 0);
    CHECK_EQ(fault_clear(&s, fault_check(&lim, 31.0f, i0)), FAULT_OV);
    CHECK_EQ(s.latched, FAULT_OV);
    /* an unrelated active condition that is not latched does not block */
    CHECK_EQ(fault_clear(&s, FAULT_ILIM), 0);
    CHECK(!fault_is_latched(&s));

    /* clear works after the condition is gone */
    fault_update(&s, FAULT_UV);
    CHECK_EQ(fault_clear(&s, fault_check(&lim, 24.0f, i0)), 0);
    CHECK(!fault_is_latched(&s));

    /* hardware bits latch through fault_latch and block clear while active */
    CHECK_EQ(fault_latch(&s, FAULT_OC_HW), FAULT_OC_HW);
    CHECK_EQ(fault_clear(&s, FAULT_OC_HW), FAULT_OC_HW);
    CHECK_EQ(fault_clear(&s, 0), 0);

    CHECK(fault_name(FAULT_OV)[0] == 'o');
    CHECK(fault_name(FAULT_HALL)[0] == 'h');
    CHECK(fault_name(1u << 30)[0] == '?');

    CHECK_DONE();
}
