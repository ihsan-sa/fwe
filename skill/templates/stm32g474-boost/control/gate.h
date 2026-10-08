/* gate.h - when the half-bridge may switch. Pure logic, so the host tests
 * cover it; hrtim.c applies its answer to OENR/ODISR.
 *
 * The high side (TA2) is the dead-time complement of the main switch (TA1).
 * At a null duty (CMP1 = 0, which hr_duty_cmp() also returns for a NaN duty
 * or a pulse shorter than HR_CMP_MIN) TA1 never sets, so TA2 stays high for
 * the whole period: the high-side GaN FET is held on, and a charged output
 * drives current back through the inductor into the input. So both outputs
 * are enabled only while the converter is armed, no fault is present and the
 * compare gives a real pulse. Zero duty, disarm and any fault disable both
 * outputs, which then sit at their idle/fault level: inactive, both FETs off.
 *
 * Re-enabling waits until a non-zero compare has reached the active CMP1:
 * CMP1 is preloaded and moves at the next repetition event, so enabling at
 * once would expose up to one period of the old null duty, high side on. The
 * first non-zero compare only moves the gate to PENDING; it goes to PWM on a
 * later call that sees `loaded`, i.e. a repetition event since the last CMP1
 * write (hrtim.c reads it from TIMxISR.REP). Counting calls instead is not
 * enough: the first control sample after arm can run inside the same period
 * as arm's own duty write, when its interrupt was pending under the mask. */
#ifndef GATE_H
#define GATE_H

#include <stdint.h>

typedef enum { GATE_OFF = 0, GATE_PENDING, GATE_PWM } gate_state_t;
typedef enum { GATE_ACT_NONE = 0, GATE_ACT_DISABLE, GATE_ACT_ENABLE } gate_act_t;

typedef struct { gate_state_t st; } gate_t;

void gate_init(gate_t *g);
/* Call on every new compare value and on every arm, disarm or fault. `cmp1`
 * is the compare now in the preload; `loaded` is 1 when the compare written
 * before it has reached the active register (a repetition event since).
 * Returns what to do to the outputs: DISABLE whenever they must be off (it is
 * safe to repeat), ENABLE once when a real pulse is known to be loaded. */
gate_act_t gate_update(gate_t *g, int armed, int faulted, uint32_t cmp1, int loaded);
/* 1 when the outputs should be on in hardware; 0 while off or pending. */
int gate_outputs_wanted(const gate_t *g);

#endif
