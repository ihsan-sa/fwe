#include "check.h"
#include "softstart.h"

int main(void)
{
    softstart_t s;
    ss_start(&s, 12.0f, 48.0f, 3600.0f); /* 36 V in 10 ms */
    CHECK_NEAR(s.ref_v, 12.0, 0);
    CHECK(!s.done);
    CHECK_NEAR(ss_step(&s, 1e-3f), 15.6, 1e-4);
    for (int i = 0; i < 8; i++)
        ss_step(&s, 1e-3f);
    CHECK(!s.done);
    CHECK(ss_step(&s, 0.5e-3f) < 48.0f);
    CHECK_NEAR(ss_step(&s, 1e-3f), 48.0, 0); /* clamps at the target */
    CHECK(s.done);
    CHECK_NEAR(ss_step(&s, 1.0f), 48.0, 0); /* holds at the target */

    /* starting at or above the target is already done and never overshoots */
    ss_start(&s, 50.0f, 48.0f, 3600.0f);
    CHECK(s.done);
    CHECK_NEAR(ss_step(&s, 1e-3f), 48.0, 0);
    CHECK_DONE();
}
