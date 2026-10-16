#ifndef FWE_PD_LIMIT_H
#define FWE_PD_LIMIT_H

#include <stdbool.h>
#include <stdint.h>

/* The power limiter: caps the volume so the amplifier rail stays under the USB-PD contract
 * the CH224A sink negotiated, before the charger trips. All of it is pure logic (core/),
 * tested on the host; the I2C and ADC reads are the ESP-IDF side's job. */

/* CH224A registers. From the CH224A datasheet as we read it; not yet checked on a board. */
#define FWE_CH224A_REG_STATUS 0x09  /* bit0 BC, bit1 QC2, bit2 QC3, bit3 PD, bit4 EPR */
#define FWE_CH224A_REG_VSEL 0x0A    /* 0 5 V, 1 9 V, 2 12 V, 3 15 V, 4 20 V, 5 28 V */
#define FWE_CH224A_REG_IMAX 0x50    /* the source's current limit, in 50 mA steps */

#define FWE_PD_CAP_FLOOR_MB (-6000) /* the most the limiter turns the volume down */
#define FWE_PD_MIN_AMP_MV 9000      /* below this (plain 5 V USB) the amplifier stays off */

typedef struct {
    uint32_t mv; /* contract voltage */
    uint32_t ma; /* contract current limit */
    bool epr;    /* an EPR (28 V) contract */
} fwe_pd_contract_t;

typedef struct {
    fwe_pd_contract_t contract;
    bool amp_on;        /* false on plain 5 V USB or no contract */
    uint32_t budget_ma; /* rail current the limiter holds the amplifier under */
    int32_t cap_mb;     /* volume cap, 0 (none) down to FWE_PD_CAP_FLOOR_MB */
} fwe_pd_limit_t;

/* Decode the CH224A's status, VSEL and IMAX registers into a contract. Returns 0, or -1 when
 * no PD contract is up (then *out is plain 5 V at the USB default 500 mA) or VSEL is one we
 * don't handle. */
int fwe_pd_decode_ch224a(uint8_t status, uint8_t vsel, uint8_t imax, fwe_pd_contract_t *out);

/* The rail current from one calibrated ADC reading, scaled by the RAIL_ISNS_REF_V and
 * RAIL_ISNS_V_PER_A that pinmap writes to board_pins.h: (adc_mv - ref) / V-per-A, rounded, 0
 * below the reference. A scale that isn't positive returns UINT32_MAX, so the limiter drops
 * to its floor rather than trusting it. */
uint32_t fwe_pd_rail_ma(int32_t adc_mv, float ref_v, float v_per_a);

/* Start the limiter on a contract: the amplifier is on only at FWE_PD_MIN_AMP_MV or more, and
 * the budget is 90% of the contract current. */
void fwe_pd_limit_init(fwe_pd_limit_t *st, const fwe_pd_contract_t *contract);

/* Feed one rail current reading; returns the new cap. Over budget the cap drops 1 dB a step,
 * at or over the contract current it drops to the floor at once, and under 80% of the budget
 * it comes back 0.1 dB a step. */
int32_t fwe_pd_limit_step(fwe_pd_limit_t *st, uint32_t rail_ma);

/* The gain to play at: the requested one, no louder than the cap (the floor if the amp is off). */
int32_t fwe_pd_limit_apply(const fwe_pd_limit_t *st, int32_t gain_mb);

#endif
