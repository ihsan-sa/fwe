#include "check.h"
#include "scale.h"

int main(void)
{
    /* PCB-0026-A numbers: 1 MHz from 170 MHz x 32, 10 ns dead time */
    CHECK_EQ(hr_period(170000000u, 1000000u, 0u), 5440);
    CHECK_EQ(hr_period(170000000u, 1000000u, 1u), 2720);
    CHECK_EQ(hr_deadtime(10u, 170000000u, 0u), 14);   /* 13.6 rounded up: 10.29 ns */
    CHECK_EQ(hr_deadtime(10u, 170000000u, 3u), 2);    /* tDTG 5.88 ns */
    CHECK_EQ(hr_deadtime(1000u, 170000000u, 0u), HR_DT_MAX);

    /* duty -> CMP1: clamp, null pulse, NaN */
    CHECK_EQ(hr_duty_cmp(0.3f, 0.82f, 5440u), 1632);
    CHECK_EQ(hr_duty_cmp(0.95f, 0.82f, 5440u), 4461);
    CHECK_EQ(hr_duty_cmp(0.0f, 0.82f, 5440u), 0);
    CHECK_EQ(hr_duty_cmp(-1.0f, 0.82f, 5440u), 0);
    CHECK_EQ(hr_duty_cmp(0.01f, 0.82f, 5440u), 0);    /* 54 counts < 0x60: skipped */
    CHECK_EQ(hr_duty_cmp(0.02f, 0.82f, 5440u), 109);
    CHECK_EQ(hr_duty_cmp(NAN, 0.82f, 5440u), 0);
    CHECK_EQ(hr_duty_cmp(1.0f, 1.0f, 5440u), 5440 - HR_CMP_MIN);
    CHECK_EQ(hr_adc_cmp(1632u, 5440u), 816);
    CHECK_EQ(hr_adc_cmp(110u, 5440u), HR_CMP_MIN);
    CHECK_EQ(hr_adc_cmp(0u, 5440u), 2720);

    /* comparator thresholds: OVP 55 V / 21, OCP 1.65 V + 17 A x 50 mV/A */
    CHECK_EQ(scale_dac_code(55.0f / 21.0f, 3.3f), 3250);
    CHECK_EQ(scale_dac_code(1.65f + 17.0f * 50.0f * 0.001f, 3.3f), 3102);
    CHECK_EQ(scale_dac_code(4.0f, 3.3f), 4095);
    CHECK_EQ(scale_dac_code(-1.0f, 3.3f), 0);
    CHECK_EQ(scale_dac_code(NAN, 3.3f), 0);

    /* ADC: mid-scale is the sim's quiet board */
    float v = scale_counts_v(2048u, 3.3f);
    CHECK_NEAR(v, 1.6504, 1e-4);
    CHECK_NEAR(v * 11.0f, 18.15, 0.01);
    CHECK_NEAR(v * 21.0f, 34.66, 0.01);
    CHECK_NEAR(scale_current_a(v, 1.65f, 50.0f, 0.001f), 0.008, 0.001);
    CHECK_NEAR(scale_current_a(2.5f, 1.65f, 50.0f, 0.001f), 17.0, 1e-4);
    CHECK(scale_current_a(2.0f, 1.65f, 0.0f, 0.001f) != scale_current_a(2.0f, 1.65f, 0.0f, 0.001f));

    /* NTC 10k B3380 with a 10k pull-up: 25 C at half rail, ~110 C at 0.247 V */
    CHECK_NEAR(scale_ntc_c(1.65f, 3.3f, 10000.0f, 10000.0f, 3380.0f), 25.0, 0.01);
    CHECK_NEAR(scale_ntc_c(0.247f, 3.3f, 10000.0f, 10000.0f, 3380.0f), 110.0, 1.0);
    float open = scale_ntc_c(3.3f, 3.3f, 10000.0f, 10000.0f, 3380.0f);
    float shorted = scale_ntc_c(0.0f, 3.3f, 10000.0f, 10000.0f, 3380.0f);
    CHECK(open != open);
    CHECK(shorted != shorted);
    CHECK_DONE();
}
