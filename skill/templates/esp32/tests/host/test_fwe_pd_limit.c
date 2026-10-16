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

typedef struct {
    uint8_t regs[256];
    int fail_reg; /* the register whose read fails, or -1 */
} fake_bus_t;

static int fake_read(void *ctx, uint8_t reg, uint8_t *val)
{
    fake_bus_t *bus = ctx;
    if (bus->fail_reg == reg) {
        return -1;
    }
    *val = bus->regs[reg];
    return 0;
}

static void test_read_ch224a(void)
{
    fake_bus_t bus = {{0}, -1};
    bus.regs[FWE_CH224A_REG_STATUS] = 0x18;
    bus.regs[FWE_CH224A_REG_VSEL] = 5;
    bus.regs[FWE_CH224A_REG_IMAX] = 100;
    fwe_pd_contract_t c;
    assert(fwe_pd_read_ch224a(fake_read, &bus, &c) == 0);
    assert(c.mv == 28000 && c.ma == 5000 && c.epr);
    /* any of the three reads failing: plain 5 V, so the amplifier stays off */
    for (int i = 0; i < 3; i++) {
        static const uint8_t regs[] = {FWE_CH224A_REG_STATUS, FWE_CH224A_REG_VSEL, FWE_CH224A_REG_IMAX};
        bus.fail_reg = regs[i];
        assert(fwe_pd_read_ch224a(fake_read, &bus, &c) == -1);
        assert(c.mv == 5000 && c.ma == 500 && !c.epr);
        fwe_pd_limit_t st;
        fwe_pd_limit_init(&st, &c);
        assert(!st.amp_on);
    }
}

static void test_rail_ma(void)
{
    /* an INA180A2-style sense: 0 V reference, 0.25 V per A */
    assert(fwe_pd_rail_ma(1000, 0.0f, 0.25f) == 4000);
    assert(fwe_pd_rail_ma(0, 0.0f, 0.25f) == 0);
    /* a 1.65 V mid-rail reference: under it reads as no current */
    assert(fwe_pd_rail_ma(1900, 1.65f, 0.5f) == 500);
    assert(fwe_pd_rail_ma(1500, 1.65f, 0.5f) == 0);
    assert(fwe_pd_rail_ma(-5, 0.0f, 0.25f) == 0);
    /* rounded to the nearest mA */
    assert(fwe_pd_rail_ma(1, 0.0f, 0.3f) == 3);
    assert(fwe_pd_rail_ma(2, 0.0f, 0.3f) == 7);
    /* no usable scale: read as over any contract, so the cap goes to the floor */
    assert(fwe_pd_rail_ma(1000, 0.0f, 0.0f) == UINT32_MAX);
    assert(fwe_pd_rail_ma(1000, 0.0f, -0.25f) == UINT32_MAX);
    fwe_pd_contract_t c = {20000, 3000, false};
    fwe_pd_limit_t st;
    fwe_pd_limit_init(&st, &c);
    assert(fwe_pd_limit_step(&st, fwe_pd_rail_ma(1000, 0.0f, 0.0f)) == FWE_PD_CAP_FLOOR_MB);
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
    test_read_ch224a();
    test_rail_ma();
    test_plain_usb_keeps_the_amp_off();
    test_limits_on_a_28v_contract();
    test_limits_on_the_20v_fallback();
    puts("test_fwe_pd_limit: ok");
    return 0;
}
