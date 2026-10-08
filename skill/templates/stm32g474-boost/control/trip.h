/* trip.h - the converter's fault latch. Pure state machine: the caller
 * measures, this decides.
 *
 * The hardware trips (a comparator into an HRTIM fault input) have already
 * forced the outputs to their safe state before firmware sees them; firmware
 * latches them from the HRTIM fault flags with trip_latch() so they are
 * reported and the converter stays off. trip_check() adds the software
 * conditions. A latched bit stays set until trip_clear(), which is refused
 * (returns the blocking bits) while any latched condition is still active. */
#ifndef TRIP_H
#define TRIP_H

#include <stdint.h>

enum {
    TRIP_OVP_HW = 1u << 0, /* output over-voltage, comparator -> HRTIM fault */
    TRIP_OCP_HW = 1u << 1, /* inductor over-current, comparator -> HRTIM fault */
    TRIP_OV     = 1u << 2, /* output over-voltage, software mirror */
    TRIP_OC     = 1u << 3, /* inductor over-current, software mirror */
    TRIP_VIN_UV = 1u << 4, /* input under the operating range */
    TRIP_VIN_OV = 1u << 5, /* input over the operating range */
    TRIP_OT     = 1u << 6, /* half-bridge over temperature */
    TRIP_COUNT  = 7
};

typedef struct {
    float vout_ov_v, i_oc_a;      /* trip when vout >= ov or il >= oc */
    float vin_uv_v, vin_ov_v;     /* trip when vin <= uv or vin >= ov */
    float t_ot_c;                 /* trip when the NTC reads >= this */
} trip_limits_t;

typedef struct { uint32_t latched; } trip_state_t;

/* Software conditions active now; a NaN measurement trips its checks. */
uint32_t trip_check(const trip_limits_t *lim, float vout_v, float il_a, float vin_v, float t_c);
void trip_init(trip_state_t *s);
/* Latch bits (software or hardware); returns those newly latched. */
uint32_t trip_latch(trip_state_t *s, uint32_t bits);
/* Clear the latch. Returns 0 when cleared, else the latched bits still
 * active (the latch is then left untouched). */
uint32_t trip_clear(trip_state_t *s, uint32_t active);
int trip_is_latched(const trip_state_t *s);
/* Short lowercase name of one bit ("ovp_hw", ...), "?" if unknown. */
const char *trip_name(uint32_t bit);

#endif
