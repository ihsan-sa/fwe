#include "check.h"
#include "pwm_math.h"

int main(void)
{
    CHECK_EQ(pwm_arr_center(170000000u, 20000u), 4250);
    CHECK_EQ(pwm_arr_center(170000000u, 0u), 0);
    CHECK_EQ(pwm_deadtime_ticks(100u, 170000000u), 17); /* 17 * 5.88 ns >= 100 ns */
    CHECK_EQ(pwm_deadtime_ticks(0u, 170000000u), 0);

    /* DTG encoding: every range, always >= the request, exact where possible */
    CHECK_EQ(pwm_dtg_encode(17), 17);
    CHECK_EQ(pwm_dtg_encode(127), 127);
    for (uint32_t t = 0; t <= 1008u; t++) {
        uint32_t got = pwm_dtg_ticks(pwm_dtg_encode(t));
        CHECK(got >= t);
        CHECK(got <= t + 15u);
    }
    CHECK_EQ(pwm_dtg_ticks(pwm_dtg_encode(128)), 128);
    CHECK_EQ(pwm_dtg_ticks(pwm_dtg_encode(254)), 254);
    CHECK_EQ(pwm_dtg_ticks(pwm_dtg_encode(504)), 504);
    CHECK_EQ(pwm_dtg_ticks(pwm_dtg_encode(1008)), 1008);
    CHECK_EQ(pwm_dtg_encode(5000), 0xFF); /* saturates */

    CHECK_EQ(pwm_duty_to_ccr(0.0f, 0.95f, 4250u), 0);
    CHECK_EQ(pwm_duty_to_ccr(0.5f, 0.95f, 4250u), 2125);
    CHECK_EQ(pwm_duty_to_ccr(1.0f, 0.95f, 4250u), 4038); /* capped at 0.95 */
    CHECK_EQ(pwm_duty_to_ccr(-0.2f, 0.95f, 4250u), 0);
    CHECK_EQ(pwm_duty_to_ccr(0.0f / 0.0f, 0.95f, 4250u), 0);

    CHECK_DONE();
}
