#include "boost.h"
#include "check.h"

/* A quasi-static boost: the output settles toward vin / (1 - d) with a lag. */
static float plant(float vout, float vin, float d)
{
    return vout + 0.05f * (vin / (1.0f - d) - vout);
}

int main(void)
{
    const float d_max = 0.85f;
    boost_ctl_t c;

    /* feedforward: 12 V -> 48 V is D 0.75, 24 V -> 48 V is D 0.5 */
    CHECK_NEAR(boost_ff(12.0f, 48.0f, d_max), 0.75, 1e-6);
    CHECK_NEAR(boost_ff(24.0f, 48.0f, d_max), 0.5, 1e-6);
    CHECK_NEAR(boost_ff(48.0f, 48.0f, d_max), 0.0, 0);   /* cannot buck */
    CHECK_NEAR(boost_ff(5.0f, 48.0f, d_max), d_max, 1e-6); /* clamped */
    CHECK_NEAR(boost_ff(0.0f, 48.0f, d_max), 0.0, 0);

    /* the loop settles on 48 V from 12 V and from 24 V */
    for (int k = 0; k < 2; k++) {
        float vin = k ? 24.0f : 12.0f, vout = vin, d = 0.0f;
        boost_init(&c, 0.002f, 20.0f, 1e-5f, d_max, 20.0f, 0.05f);
        for (int i = 0; i < 4000; i++) {
            d = boost_step(&c, 48.0f, vout, vin, 5.0f);
            vout = plant(vout, vin, d);
        }
        CHECK_NEAR(vout, 48.0, 0.05);
        CHECK(!c.limiting);
        /* a 1 V droop the feedforward does not see is trimmed out by the PI */
        for (int i = 0; i < 4000; i++) {
            d = boost_step(&c, 48.0f, vout, vin, 5.0f);
            vout = plant(vout, vin, d) - 0.05f;
        }
        CHECK(vout > 47.0f);
        CHECK(d > boost_ff(vin, 48.0f, d_max));
    }

    /* over the current limit the duty folds back and the integrator holds */
    boost_init(&c, 0.002f, 20.0f, 1e-5f, d_max, 20.0f, 0.05f);
    c.v.integ = 0.01f;
    float d_lim = boost_step(&c, 48.0f, 40.0f, 12.0f, 22.0f); /* 2 A over */
    CHECK(c.limiting);
    CHECK_NEAR(c.v.integ, 0.01f, 0); /* held */
    /* ff 0.75 + kp * 8 V + integ 0.01 - 0.05 * 2 A */
    CHECK_NEAR(d_lim, 0.75 + 0.016 + 0.01 - 0.1, 1e-5);
    CHECK_NEAR(boost_step(&c, 48.0f, 40.0f, 12.0f, 60.0f), 0.0, 0); /* fully folded back */

    /* a NaN reading switches nothing */
    CHECK_NEAR(boost_step(&c, 48.0f, 0.0f / 0.0f, 12.0f, 0.0f), 0.0, 0);
    CHECK_DONE();
}
