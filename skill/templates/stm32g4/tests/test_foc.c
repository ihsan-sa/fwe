#include "check.h"
#include "foc.h"

int main(void)
{
    /* Clarke of a balanced set: a = 1, b = c = -0.5 -> alpha 1, beta 0 */
    foc_ab_t ab = foc_clarke(1.0f, -0.5f);
    CHECK_NEAR(ab.alpha, 1.0, 1e-6);
    CHECK_NEAR(ab.beta, 0.0, 1e-6);
    /* b = 1 at 120 degrees: a = -0.5, b = 1 -> alpha -0.5, beta sqrt(3)/2 */
    ab = foc_clarke(-0.5f, 1.0f);
    CHECK_NEAR(ab.alpha, -0.5, 1e-6);
    CHECK_NEAR(ab.beta, 0.8660254, 1e-6);

    /* Clarke -> inverse Clarke round trip, over many angles */
    for (int k = 0; k < 36; k++) {
        float th = (float)k * 0.17453293f;
        float a = cosf(th), b = cosf(th - 2.0943951f), c = cosf(th + 2.0943951f);
        foc_abc_t r = foc_inv_clarke(foc_clarke(a, b));
        CHECK_NEAR(r.a, a, 1e-5);
        CHECK_NEAR(r.b, b, 1e-5);
        CHECK_NEAR(r.c, c, 1e-5);
        /* Park at the same angle turns the rotating vector into d = 1, q = 0 */
        foc_dq_t dq = foc_park(foc_clarke(a, b), sinf(th), cosf(th));
        CHECK_NEAR(dq.d, 1.0, 1e-5);
        CHECK_NEAR(dq.q, 0.0, 1e-5);
        foc_ab_t back = foc_inv_park(dq, sinf(th), cosf(th));
        CHECK_NEAR(back.alpha, cosf(th), 1e-5);
        CHECK_NEAR(back.beta, sinf(th), 1e-5);
    }
    /* Park known value: theta = 90 deg, alpha 0, beta 1 -> d 1, q 0 */
    foc_ab_t in = { 0.0f, 1.0f };
    foc_dq_t dq = foc_park(in, 1.0f, 0.0f);
    CHECK_NEAR(dq.d, 1.0, 1e-6);
    CHECK_NEAR(dq.q, 0.0, 1e-6);

    /* SVPWM: zero vector is the 0.5 centre on every phase */
    foc_ab_t zero = { 0.0f, 0.0f };
    foc_abc_t d = foc_svpwm(zero, 24.0f, 0.95f);
    CHECK_NEAR(d.a, 0.5, 1e-6);
    CHECK_NEAR(d.b, 0.5, 1e-6);
    CHECK_NEAR(d.c, 0.5, 1e-6);
    /* edge of the linear range on alpha: |v| = vbus/sqrt(3) -> 0.9330 / 0.0670 */
    foc_ab_t edge = { 24.0f * FOC_INV_SQRT3, 0.0f };
    d = foc_svpwm(edge, 24.0f, 1.0f);
    CHECK_NEAR(d.a, 0.9330127, 1e-5);
    CHECK_NEAR(d.b, 0.0669873, 1e-5);
    CHECK_NEAR(d.c, 0.0669873, 1e-5);
    /* line-to-line amplitude is preserved: duty_a - duty_b = (va - vb)/vbus */
    foc_ab_t half = { 6.0f, 0.0f };
    d = foc_svpwm(half, 24.0f, 1.0f);
    CHECK_NEAR(d.a - d.b, (6.0 - (-3.0)) / 24.0, 1e-5);
    CHECK_NEAR(0.5f * (d.a + d.b), 0.5, 1e-5); /* max and min phases straddle 0.5 */
    /* clamp: a huge vector saturates at max_duty and at 0 */
    foc_ab_t big = { 100.0f, 0.0f };
    d = foc_svpwm(big, 24.0f, 0.95f);
    CHECK_NEAR(d.a, 0.95, 1e-6);
    CHECK_NEAR(d.b, 0.0, 1e-6);
    CHECK_NEAR(d.c, 0.0, 1e-6);
    /* no bus: zero vector, still clamped */
    d = foc_svpwm(edge, 0.0f, 0.4f);
    CHECK_NEAR(d.a, 0.4, 1e-6);
    CHECK_NEAR(d.b, 0.4, 1e-6);

    CHECK_DONE();
}
