#include "check.h"
#include "sixstep.h"

int main(void)
{
    const uint8_t fwd[6] = { 1, 3, 2, 6, 4, 5 };
    sixstep_drive_t d;

    /* every valid code drives exactly one high and one low phase */
    for (uint8_t h = 1; h <= 6; h++) {
        CHECK_EQ(sixstep_drive(h, 0, &d), 0);
        CHECK_EQ((d.a == 1) + (d.b == 1) + (d.c == 1), 1);
        CHECK_EQ((d.a == -1) + (d.b == -1) + (d.c == -1), 1);
        CHECK_EQ(d.a + d.b + d.c, 0);
    }
    /* forward hall sequence walks the steps 0..5 in order */
    for (int k = 0; k < 6; k++) CHECK_EQ(sixstep_step(fwd[k]), k);
    /* known steps */
    sixstep_drive(1, 0, &d);
    CHECK(d.a == 1 && d.b == -1 && d.c == 0);
    sixstep_drive(5, 0, &d);
    CHECK(d.a == 0 && d.b == -1 && d.c == 1);
    /* reverse swaps high and low */
    sixstep_drive(1, 1, &d);
    CHECK(d.a == -1 && d.b == 1 && d.c == 0);

    /* invalid codes: 0 and 7 (and anything wider) are faults, bridge floats */
    CHECK_EQ(sixstep_step(0), -1);
    CHECK_EQ(sixstep_step(7), -1);
    CHECK_EQ(sixstep_step(200), -1);
    d.a = 1;
    CHECK_EQ(sixstep_drive(0, 0, &d), -1);
    CHECK(d.a == 0 && d.b == 0 && d.c == 0);
    CHECK_EQ(sixstep_drive(7, 1, &d), -1);

    CHECK_DONE();
}
