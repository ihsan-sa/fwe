#include "check.h"
#include "pi.h"

int main(void)
{
    pi_t p;
    pi_init(&p, 0.5f, 10.0f, 0.001f, -1.0f, 1.0f);
    /* proportional only on the first step: 0.5*0.2 + 10*0.001*0.2 */
    CHECK_NEAR(pi_step(&p, 0.2f), 0.1 + 0.002, 1e-6);

    /* integral accumulates */
    pi_reset(&p);
    for (int k = 0; k < 10; k++) pi_step(&p, 1.0f);
    CHECK_NEAR(p.integ, 0.1, 1e-5);

    /* windup: a long large error saturates; the integrator must stay bounded */
    pi_reset(&p);
    float out = 0.0f;
    for (int k = 0; k < 100000; k++) out = pi_step(&p, 10.0f);
    CHECK_NEAR(out, 1.0, 0.0);
    CHECK(p.integ <= 1.0f);
    /* then a reversal leaves saturation at once, not after unwinding */
    out = pi_step(&p, -1.0f);
    CHECK(out < 1.0f);
    int steps = 0;
    while (out > 0.0f && steps < 1000) { out = pi_step(&p, -1.0f); steps++; }
    CHECK(steps < 200); /* integ <= 1, falls 0.01/step with kp term -0.5 */

    /* output clamp both ways */
    pi_reset(&p);
    CHECK_NEAR(pi_step(&p, -50.0f), -1.0, 0.0);
    CHECK(p.integ >= -1.0f);

    CHECK_DONE();
}
