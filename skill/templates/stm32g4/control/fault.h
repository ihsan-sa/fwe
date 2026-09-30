/* fault.h - fault latch. Pure state machine: the caller measures, this decides.
 *
 * fault_check() turns measurements into the set of conditions active now.
 * fault_update() latches them; a latched bit stays set until fault_clear(),
 * which is refused (returns the blocking bits) while any latched condition is
 * still active. Hardware sources (the TIM1 break) are latched with
 * fault_latch() and report their own "still active" bits to fault_clear(). */
#ifndef FAULT_H
#define FAULT_H

#include <stdint.h>

enum {
    FAULT_OV    = 1u << 0, /* bus overvoltage */
    FAULT_UV    = 1u << 1, /* bus undervoltage */
    FAULT_OC    = 1u << 2, /* |i| over the trip level (software mirror of the hw trip) */
    FAULT_ILIM  = 1u << 3, /* |i| over the software limit */
    FAULT_OC_HW = 1u << 4, /* hardware comparator break */
    FAULT_HALL  = 1u << 5, /* invalid hall state */
    FAULT_COUNT = 6
};

typedef struct {
    float vbus_ov_v, vbus_uv_v; /* trip when vbus >= ov or vbus <= uv */
    float i_trip_a, i_limit_a;  /* trip when |i| >= limit on any phase */
} fault_limits_t;

typedef struct { uint32_t latched; } fault_state_t;

uint32_t fault_check(const fault_limits_t *lim, float vbus_v, const float i_a[3]);
void fault_init(fault_state_t *s);
/* Latch active conditions; returns the bits that were newly latched. */
uint32_t fault_update(fault_state_t *s, uint32_t active);
/* Latch extra bits from outside (hardware); returns the newly latched ones. */
uint32_t fault_latch(fault_state_t *s, uint32_t bits);
/* Clear the latch. Returns 0 when cleared, else the latched bits still active
 * (the latch is then left untouched). */
uint32_t fault_clear(fault_state_t *s, uint32_t active);
int fault_is_latched(const fault_state_t *s);
/* Short lowercase name of one fault bit ("ov", "uv", ...), "?" if unknown. */
const char *fault_name(uint32_t bit);

#endif
