#include "check.h"
#include "sense.h"

/* PCB-0018-A numbers: INA240A1 (x20), 3 mOhm shunt, 1.65 V mid -> 60 mV/A */
#define GAIN 20.0f
#define SHUNT 0.003f
#define REF 1.65f

int main(void)
{
    CHECK_NEAR(sense_counts_to_v(0, 3.3f), 0.0, 1e-6);
    CHECK_NEAR(sense_counts_to_v(4095, 3.3f), 3.3, 1e-5);
    CHECK_NEAR(sense_counts_to_v(2048, 3.3f), 1.650403, 1e-5);

    CHECK_NEAR(sense_current_a(1.65f, REF, GAIN, SHUNT), 0.0, 1e-4);
    CHECK_NEAR(sense_current_a(1.71f, REF, GAIN, SHUNT), 1.0, 1e-3);
    CHECK_NEAR(sense_current_a(1.59f, REF, GAIN, SHUNT), -1.0, 1e-3);
    CHECK_NEAR(sense_current_a(3.3f, REF, GAIN, SHUNT), 27.5, 1e-3);
    CHECK_NEAR(sense_current_a(0.0f, REF, GAIN, SHUNT), -27.5, 1e-3);
    CHECK_NEAR(sense_current_a(1.0f, REF, 0.0f, SHUNT), 0.0, 0.0); /* no divide by 0 */
    CHECK_NEAR(sense_current_to_v(20.0f, REF, GAIN, SHUNT), 2.85, 1e-5);
    CHECK_NEAR(sense_current_a(sense_current_to_v(7.0f, REF, GAIN, SHUNT), REF, GAIN, SHUNT), 7.0, 1e-4);

    /* VBUS divider x16 (150k/10k): 1.5 V at the pin is 24 V */
    CHECK_NEAR(sense_vbus_v(1.5f, 16.0f), 24.0, 1e-5);
    CHECK_NEAR(sense_vbus_v(sense_counts_to_v(4095, 3.3f), 16.0f), 52.8, 1e-3);

    sense_avg_t avg;
    sense_avg_reset(&avg);
    CHECK_NEAR(sense_avg_mean(&avg, 1.65f), 1.65, 1e-6); /* fallback when empty */
    for (int k = 0; k < 100; k++) sense_avg_add(&avg, (k & 1) ? 1.66f : 1.64f);
    CHECK_EQ(avg.n, 100);
    CHECK_NEAR(sense_avg_mean(&avg, 0.0f), 1.65, 1e-5);
    CHECK(sense_offset_ok(1.70f, 1.65f, 0.15f));
    CHECK(!sense_offset_ok(1.85f, 1.65f, 0.15f));
    CHECK(!sense_offset_ok(0.0f, 1.65f, 0.15f));

    CHECK_DONE();
}
