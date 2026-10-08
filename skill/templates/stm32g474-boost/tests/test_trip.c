#include "check.h"
#include "trip.h"

int main(void)
{
    const trip_limits_t lim = { 52.0f, 15.0f, 10.0f, 28.0f, 110.0f };
    trip_state_t s;
    trip_init(&s);

    CHECK_EQ(trip_check(&lim, 48.0f, 5.0f, 12.0f, 40.0f), 0);
    CHECK_EQ(trip_check(&lim, 52.0f, 5.0f, 12.0f, 40.0f), TRIP_OV);
    CHECK_EQ(trip_check(&lim, 48.0f, 15.0f, 12.0f, 40.0f), TRIP_OC);
    CHECK_EQ(trip_check(&lim, 48.0f, 5.0f, 10.0f, 40.0f), TRIP_VIN_UV);
    CHECK_EQ(trip_check(&lim, 48.0f, 5.0f, 28.0f, 40.0f), TRIP_VIN_OV);
    CHECK_EQ(trip_check(&lim, 48.0f, 5.0f, 12.0f, 110.0f), TRIP_OT);
    CHECK_EQ(trip_check(&lim, 0.0f / 0.0f, 5.0f, 12.0f, 40.0f), TRIP_OV); /* NaN trips */

    /* a hardware trip latches, is reported once as new, and stays latched */
    CHECK(!trip_is_latched(&s));
    CHECK_EQ(trip_latch(&s, TRIP_OCP_HW), TRIP_OCP_HW);
    CHECK_EQ(trip_latch(&s, TRIP_OCP_HW), 0);
    CHECK(trip_is_latched(&s));
    CHECK_EQ(trip_latch(&s, 0), 0);
    CHECK_EQ(s.latched, TRIP_OCP_HW);

    /* clear is refused while the latched source is still active */
    CHECK_EQ(trip_clear(&s, TRIP_OCP_HW | TRIP_OT), TRIP_OCP_HW);
    CHECK_EQ(s.latched, TRIP_OCP_HW);
    /* an active condition that is not latched does not block */
    CHECK_EQ(trip_clear(&s, TRIP_OT), 0);
    CHECK(!trip_is_latched(&s));

    CHECK(trip_name(TRIP_OVP_HW)[0] == 'o' && trip_name(TRIP_OT)[1] == 't');
    CHECK(trip_name(1u << 20)[0] == '?');
    CHECK(trip_name(TRIP_ADC)[0] == 'a');
    CHECK(trip_name(1u << TRIP_COUNT)[0] == '?');
    CHECK_DONE();
}
