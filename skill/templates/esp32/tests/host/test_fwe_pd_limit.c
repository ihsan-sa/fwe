#include <assert.h>
#include <stdio.h>

#include "fwe_pd_limit.h"

static void test_decode(void)
{
    fwe_pd_contract_t c;
    /* 28 V EPR contract at 5 A */
    assert(fwe_pd_decode_ch224a(0x18, 5, 100, &c) == 0);
    assert(c.mv == 28000 && c.ma == 5000 && c.epr);
    /* 28 V asked for, the source has no EPR: its 20 V fallback */
    assert(fwe_pd_decode_ch224a(0x08, 5, 60, &c) == 0);
    assert(c.mv == 20000 && c.ma == 3000 && !c.epr);
    /* a plain 20 V contract */
    assert(fwe_pd_decode_ch224a(0x08, 4, 65, &c) == 0);
    assert(c.mv == 20000 && c.ma == 3250);
    /* no PD (BC only): plain 5 V USB */
    assert(fwe_pd_decode_ch224a(0x01, 4, 65, &c) == -1);
    assert(c.mv == 5000 && c.ma == 500 && !c.epr);
    /* a VSEL we don't handle (PPS, AVS) */
    assert(fwe_pd_decode_ch224a(0x08, 6, 65, &c) == -1);
    assert(c.mv == 5000);
}

static void test_plain_usb_keeps_the_amp_off(void)
{
    fwe_pd_contract_t c = {5000, 3000, false};
    fwe_pd_limit_t st;
    fwe_pd_limit_init(&st, &c);
    assert(!st.amp_on);
    assert(fwe_pd_limit_step(&st, 0) == FWE_PD_CAP_FLOOR_MB);
    assert(fwe_pd_limit_apply(&st, -2000) == FWE_PD_CAP_FLOOR_MB);
}

static void test_limits_on_a_28v_contract(void)
{
    fwe_pd_contract_t c = {28000, 5000, true};
    fwe_pd_limit_t st;
    fwe_pd_limit_init(&st, &c);
    assert(st.amp_on && st.budget_ma == 4500 && st.cap_mb == 0);
    assert(fwe_pd_limit_apply(&st, -1500) == -1500);
    /* under budget, above the release point: the cap holds */
    assert(fwe_pd_limit_step(&st, 4000) == 0);
    /* over budget: 1 dB a step */
    assert(fwe_pd_limit_step(&st, 4600) == -100);
    assert(fwe_pd_limit_step(&st, 4600) == -200);
    assert(fwe_pd_limit_apply(&st, 0) == -200);
    assert(fwe_pd_limit_apply(&st, -1500) == -1500);
    /* well under budget: 0.1 dB a step back, never over 0 */
    assert(fwe_pd_limit_step(&st, 1000) == -190);
    for (int i = 0; i < 100; i++) {
        fwe_pd_limit_step(&st, 1000);
    }
    assert(st.cap_mb == 0);
    /* at the contract current: straight to the floor, and no lower */
    assert(fwe_pd_limit_step(&st, 5000) == FWE_PD_CAP_FLOOR_MB);
    assert(fwe_pd_limit_step(&st, 4600) == FWE_PD_CAP_FLOOR_MB);
}

static void test_limits_on_the_20v_fallback(void)
{
    fwe_pd_contract_t c;
    fwe_pd_limit_t st;
    fwe_pd_decode_ch224a(0x08, 5, 60, &c);
    fwe_pd_limit_init(&st, &c);
    assert(st.amp_on && st.budget_ma == 2700);
    assert(fwe_pd_limit_step(&st, 2800) == -100);
}

int main(void)
{
    test_decode();
    test_plain_usb_keeps_the_amp_off();
    test_limits_on_a_28v_contract();
    test_limits_on_the_20v_fallback();
    puts("test_fwe_pd_limit: ok");
    return 0;
}
