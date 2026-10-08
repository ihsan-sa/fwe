/* test_hrtim_arm.c - src/hrtim.c's arm, duty and disarm paths, compiled on
 * the host over plain-memory registers (hrtim_stub.h). The order of the calls
 * inside hrtim.c is what keeps arm safe: s_armed is set before the gate
 * looks at it, the gate is told whether the pulse has loaded, and disarm
 * resets the gate. test_gate.c only sees gate.c's logic; this test fails when
 * hrtim.c calls it in the wrong order. After every step it checks the one
 * thing that matters: the outputs are never enabled while the active CMP1
 * is null (TA2, the high side, held on for the whole period). Not visible
 * here: the order of the REP read and its ICR clear inside one call, because
 * the stub applies the clear only when the call returns. */
#include <string.h>
#include "check.h"
#include "hrtim_stub.h"
#include "../src/hrtim.c"

#define HR (fake_hrtim.sCommonRegs)
#define TM (fake_hrtim.sTimerxRegs[0])
#define BOTH (HRTIM_OENR_TA1OEN | HRTIM_OENR_TA2OEN)

static uint32_t s_en;      /* the output enables the hardware would hold */
static uint32_t s_active;  /* the active CMP1 (the preload moves at REP) */
static int s_bad;          /* steps that left the outputs on with a null CMP1 */

/* before a call: OENR reads the enables, the write-only registers read 0 */
static void hw_prime(void)
{
    HR.OENR = s_en;
    HR.ODISR = 0u;
    TM.TIMxICR = 0u;
}

/* after a call: apply what the writes would have done, then check */
static void hw_settle(void)
{
    if (HR.ODISR) s_en &= ~HR.ODISR;
    else if (HR.OENR != s_en) s_en |= HR.OENR & BOTH;
    if (TM.TIMxICR & HRTIM_TIMICR_REPC) TM.TIMxISR &= ~HRTIM_TIMISR_REP;
    HR.OENR = s_en;
    if (s_en && s_active == 0u) s_bad++;
}

/* a repetition event: the preload reaches the active CMP1 */
static void period(void)
{
    s_active = TM.CMP1xR;
    TM.TIMxISR |= HRTIM_TIMISR_REP;
    if (s_en && s_active == 0u) s_bad++;
}

static void duty(float d) { hw_prime(); hrtim_set_duty(d); hw_settle(); }
static void arm(void) { hw_prime(); hrtim_outputs_on(); hw_settle(); }
static void disarm(void) { hw_prime(); hrtim_outputs_off(); hw_settle(); }

static void boot(void)
{
    memset(&fake_hrtim, 0, sizeof fake_hrtim);
    s_en = s_active = 0u;
    HR.ISR = HRTIM_ISR_DLLRDY;
    CHECK_EQ(hrtim_init(), 0);
    period();
}

int main(void)
{
    flt_t ov, oc;  /* the board's two fault inputs (gen/board_pins.h) */
    CHECK_EQ(flt_of(TRIP_OVP_FLT, &ov), 0);
    CHECK_EQ(flt_of(TRIP_OCP_FLT, &oc), 0);

    /* safety_arm's order: the feedforward duty, then arm. The first control
     * sample can run before the next period (its interrupt was pending under
     * the mask), and must not enable over the old null CMP1. */
    boot();
    duty(0.4f);
    arm();
    CHECK_EQ(s_en, 0u);
    duty(0.4f);
    CHECK_EQ(s_en, 0u);
    period();
    duty(0.4f);
    CHECK_EQ(s_en, BOTH);
    CHECK(s_active != 0u);
    CHECK(!hrtim_outputs_dropped());

    /* zero duty while running: both off at once, then on again only after a
     * real pulse has been loaded */
    duty(0.0f);
    CHECK_EQ(s_en, 0u);
    period();
    duty(0.4f);
    CHECK_EQ(s_en, 0u);
    duty(0.4f);
    CHECK_EQ(s_en, 0u);
    period();
    duty(0.4f);
    CHECK_EQ(s_en, BOTH);

    /* disarm: off, and the next arm goes through the whole wait again (a
     * disarm that left the gate switching would never re-enable) */
    disarm();
    CHECK_EQ(s_en, 0u);
    CHECK(!hrtim_outputs_dropped());
    period();
    duty(0.4f);
    CHECK_EQ(s_en, 0u);            /* disarmed: a duty write switches nothing on */
    arm();
    CHECK_EQ(s_en, 0u);
    period();
    duty(0.4f);
    CHECK_EQ(s_en, BOTH);

    /* the reverse order (arm, then the duty) is just as safe */
    disarm();
    period();
    arm();
    duty(0.4f);
    CHECK_EQ(s_en, 0u);
    period();
    duty(0.4f);
    CHECK_EQ(s_en, BOTH);

    /* a fault flag: off at the next duty write and stays off */
    HR.ISR |= ov.isr;
    duty(0.4f);
    CHECK_EQ(s_en, 0u);
    period();
    duty(0.4f);
    CHECK_EQ(s_en, 0u);
    HR.ISR &= ~ov.isr;
    disarm();

    /* a dropped output (the hardware cleared an enable) is reported */
    arm();
    duty(0.4f);
    period();
    duty(0.4f);
    CHECK_EQ(s_en, BOTH);
    s_en &= ~HRTIM_OENR_TA2OEN;
    HR.OENR = s_en;
    CHECK(hrtim_outputs_dropped());

    /* the fault set-up is locked once both inputs are on (RM0440 28.3.17) */
    boot();
    CHECK_EQ(hrtim_faults_init(), 0);
    uint32_t fltr = ov.timer_en | oc.timer_en | HRTIM_FLTR_FLTLCK;
    CHECK_EQ(TM.FLTxR & fltr, fltr);
    CHECK_EQ(*ov.inr & (ov.en | ov.lck), ov.en | ov.lck);
    CHECK_EQ(*oc.inr & (oc.en | oc.lck), oc.en | oc.lck);

    CHECK_EQ(s_bad, 0);
    CHECK_DONE();
}
