/* test_board.c - the one test that reads gen/board_pins.h and config/fw_config.h:
 * it checks the board-derived constants make sense for the control code.
 * The other tests use literal numbers so they run for any board. */
#include "check.h"
#include "board_pins.h"
#include "fw_config.h"
#include "sense.h"

int main(void)
{
    const float gains[3] = { ISENSE_A_GAIN, ISENSE_B_GAIN, ISENSE_C_GAIN };
    const float shunts[3] = { ISENSE_A_SHUNT_OHM, ISENSE_B_SHUNT_OHM, ISENSE_C_SHUNT_OHM };
    const float refs[3] = { ISENSE_A_REF_V, ISENSE_B_REF_V, ISENSE_C_REF_V };

    CHECK(sizeof(BOARD_ID) > 1);
    CHECK(RAIL_VDDA_V > 1.6f && RAIL_VDDA_V < 3.7f);
    CHECK(VBUS_SENSE_RATIO > 1.0f);
    /* the OV trip must be inside the VBUS ADC range, or it can never fire */
    CHECK(VBUS_OV_V < sense_vbus_v(RAIL_VDDA_V, VBUS_SENSE_RATIO));
    CHECK(VBUS_UV_V < VBUS_OV_V);
    CHECK(I_LIMIT_A <= I_TRIP_A);
    CHECK(MAX_DUTY > 0.0f && MAX_DUTY <= 1.0f);

    for (int k = 0; k < 3; k++) {
        CHECK(gains[k] > 0.0f && shunts[k] > 0.0f);
        CHECK(refs[k] > 0.0f && refs[k] < RAIL_VDDA_V);
        /* 0 A at the reference; the trip level is inside the ADC and COMP range */
        CHECK_NEAR(sense_current_a(refs[k], refs[k], gains[k], shunts[k]), 0.0, 1e-6);
        float v_trip = sense_current_to_v(I_TRIP_A, refs[k], gains[k], shunts[k]);
        CHECK(v_trip < RAIL_VDDA_V);
        printf("phase %c: %.1f mV/A, full scale +%.2f A, trip at %.3f V\n", 'A' + k,
               (double)(gains[k] * shunts[k] * 1000.0f),
               (double)sense_current_a(RAIL_VDDA_V, refs[k], gains[k], shunts[k]), (double)v_trip);
    }
    CHECK_DONE();
}
