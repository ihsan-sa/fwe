#include "fwe_pd_limit.h"

#define STATUS_PD 0x08u
#define STATUS_EPR 0x10u
#define IMAX_STEP_MA 50u
#define USB_DEFAULT_MA 500u
#define ATTACK_MB 100
#define RELEASE_MB 10

static const uint32_t vsel_mv[] = {5000, 9000, 12000, 15000, 20000, 28000};

int fwe_pd_decode_ch224a(uint8_t status, uint8_t vsel, uint8_t imax, fwe_pd_contract_t *out)
{
    out->mv = 5000;
    out->ma = USB_DEFAULT_MA;
    out->epr = false;
    if (!(status & (STATUS_PD | STATUS_EPR)) || vsel >= sizeof vsel_mv / sizeof vsel_mv[0]) {
        return -1;
    }
    out->mv = vsel_mv[vsel];
    out->ma = (uint32_t)imax * IMAX_STEP_MA;
    out->epr = (status & STATUS_EPR) != 0;
    if (out->mv > 20000 && !out->epr) {
        out->mv = 20000; /* 28 V asked for but no EPR contract: the source gives its 20 V fallback */
    }
    return 0;
}

void fwe_pd_limit_init(fwe_pd_limit_t *st, const fwe_pd_contract_t *contract)
{
    st->contract = *contract;
    st->amp_on = contract->mv >= FWE_PD_MIN_AMP_MV && contract->ma > 0;
    st->budget_ma = st->amp_on ? contract->ma / 10u * 9u : 0;
    st->cap_mb = st->amp_on ? 0 : FWE_PD_CAP_FLOOR_MB;
}

int32_t fwe_pd_limit_step(fwe_pd_limit_t *st, uint32_t rail_ma)
{
    if (!st->amp_on) {
        return st->cap_mb = FWE_PD_CAP_FLOOR_MB;
    }
    if (rail_ma >= st->contract.ma) {
        st->cap_mb = FWE_PD_CAP_FLOOR_MB;
    } else if (rail_ma > st->budget_ma) {
        st->cap_mb -= ATTACK_MB;
    } else if (rail_ma < st->budget_ma / 5u * 4u) {
        st->cap_mb += RELEASE_MB;
    }
    if (st->cap_mb < FWE_PD_CAP_FLOOR_MB) {
        st->cap_mb = FWE_PD_CAP_FLOOR_MB;
    }
    if (st->cap_mb > 0) {
        st->cap_mb = 0;
    }
    return st->cap_mb;
}

int32_t fwe_pd_limit_apply(const fwe_pd_limit_t *st, int32_t gain_mb)
{
    if (!st->amp_on) {
        return FWE_PD_CAP_FLOOR_MB;
    }
    return gain_mb > st->cap_mb ? st->cap_mb : gain_mb;
}
