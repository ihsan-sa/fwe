/* safety.c - the control sample and its supervision.
 *
 * safety_sample() runs in the ADC interrupt, once per CTRL_DIV PWM periods:
 * measure -> trip_check -> soft start or regulation -> duty. A software trip
 * only latches while the converter switches (with the bridge off an input
 * under VIN_UV_V is just an unpowered bench); the HRTIM fault flags latch
 * always, because the comparators watch the real power stage either way.
 * Any trip while switching drops both outputs inside the same sample.
 *
 * safety_poll() runs in the main loop: it latches the FLTn flags (a fault
 * before arm), stops the bridge if the control sample stops for
 * ADC_STALE_MS (TRIP_ADC), notices outputs the hardware dropped, applies the
 * thermal derating and reports each newly latched trip once as an EVT line.
 * It touches the latch and the mode only with interrupts masked. */
#include <math.h>
#include "app.h"
#include "boost.h"
#include "softstart.h"

#define CTRL_DT ((float)CTRL_DIV / (float)PWM_FREQ_HZ)
#define SW_TRIPS (TRIP_OV | TRIP_OC | TRIP_VIN_UV | TRIP_VIN_OV | TRIP_OT)

static const trip_limits_t k_limits = { VOUT_OV_V, I_TRIP_A, VIN_UV_V, VIN_OV_V, T_SHUTDOWN_C };

static boost_ctl_t s_ctl;
static softstart_t s_ss;
static float s_open_d;
static uint32_t s_seen_samples, s_seen_ms;

static void stop_locked(void)
{
    hrtim_outputs_off();
    g_app.mode = MODE_OFF;
}

void safety_init(void)
{
    trip_init(&g_app.trips);
    boost_init(&s_ctl, CTRL_KP, CTRL_KI, CTRL_DT, D_MAX, I_LIMIT_A, K_ILIM);
    g_app.mode = MODE_OFF;
    g_app.vref_v = 0.0f;
    s_seen_ms = millis();
}

void safety_sample(void)
{
    adc_convert();
    g_app.samples++;
    uint32_t a = trip_check(&k_limits, g_app.vout_v, g_app.il_a, g_app.vin_v, g_app.temp_c);
    g_app.active = a;
    ctl_mode_t m = g_app.mode;
    if (m == MODE_OFF) return;

    uint32_t trips = (a & SW_TRIPS) | hrtim_fault_flags();
    if (trips) {
        stop_locked();
        g_app.evt |= trip_latch(&g_app.trips, trips);
        return;
    }
    float d;
    if (m == MODE_OPEN) {
        d = s_open_d;
    } else {
        g_app.vref_v = ss_step(&s_ss, CTRL_DT);
        if (m == MODE_SOFTSTART && s_ss.done) g_app.mode = MODE_RUN;
        d = boost_step(&s_ctl, g_app.vref_v, g_app.vout_v, g_app.vin_v, g_app.il_a);
    }
    hrtim_set_duty(d);
}

uint32_t safety_active_now(void)
{
    return g_app.active | comp_active();
}

/* refuse to switch on a latched trip, a live condition, or an unarmed trip
 * path; returns 0 with interrupts still masked so the caller can finish */
static int may_switch(void)
{
    if (trip_is_latched(&g_app.trips)) return -1;
    if (safety_active_now() || hrtim_fault_flags()) return -2;
    if (!g_app.hw_ok || !g_app.adc_ok) return -3;
    return 0;
}

int safety_arm(void)
{
    __disable_irq();
    int r = g_app.mode != MODE_OFF ? -5 : may_switch();
    if (r == 0) {
        /* start the ramp at the present output, not the input, so the
         * feedforward duty matches the charged output caps. A duty of 0
         * (output at or above the input) no longer holds the high side on:
         * hrtim.c keeps both outputs off until the duty is a real pulse */
        boost_reset(&s_ctl);
        ss_start(&s_ss, fmaxf(g_app.vin_v, g_app.vout_v), VOUT_TARGET_V, SS_SLEW_V_PER_S);
        g_app.vref_v = s_ss.ref_v;
        hrtim_set_duty(boost_ff(g_app.vin_v, g_app.vref_v, D_MAX));
        g_app.mode = MODE_SOFTSTART;
        hrtim_outputs_on(); /* enabled from a later sample; a refusal shows in safety_poll */
    }
    __enable_irq();
    return r;
}

int safety_open(float d)
{
    if (!(d >= 0.0f)) return -6;
    if (d > D_MAX) d = D_MAX;
    __disable_irq();
    int r = 0;
    if (g_app.mode == MODE_SOFTSTART || g_app.mode == MODE_RUN) r = -5; /* regulating: disarm first */
    else if (g_app.mode == MODE_OPEN) { s_open_d = d; hrtim_set_duty(d); }
    else if ((r = may_switch()) == 0) {
        s_open_d = d;
        hrtim_set_duty(d);
        g_app.vref_v = 0.0f;
        g_app.mode = MODE_OPEN;
        hrtim_outputs_on(); /* enabled from a later sample; a refusal shows in safety_poll */
    }
    __enable_irq();
    return r;
}

void safety_disarm(void)
{
    __disable_irq();
    stop_locked();
    __enable_irq();
}

const char *safety_mode_name(void)
{
    static const char *const names[] = { "off", "softstart", "run", "open" };
    ctl_mode_t m = g_app.mode;
    return (unsigned)m < 4u ? names[m] : "?";
}

void safety_poll(void)
{
    uint32_t now = millis();
    uint32_t n = g_app.samples;
    int stale = 0;
    if (n != s_seen_samples) { s_seen_samples = n; s_seen_ms = now; }
    else if (now - s_seen_ms > ADC_STALE_MS) stale = 1;
    g_app.adc_ok = !stale;

    /* above T_DERATE_C, cap the average current at P_DERATE_W from the input */
    float t = g_app.temp_c, vin = g_app.vin_v;
    g_app.derated = t > T_DERATE_C && vin > VIN_UV_V;
    float lim = g_app.derated ? P_DERATE_W / vin : I_LIMIT_A;
    s_ctl.i_limit_a = lim < I_LIMIT_A ? lim : I_LIMIT_A;

    __disable_irq();
    uint32_t fresh = trip_latch(&g_app.trips, hrtim_fault_flags());
    if (g_app.mode != MODE_OFF) {
        if (stale) fresh |= trip_latch(&g_app.trips, TRIP_ADC);
        if (trip_is_latched(&g_app.trips) || hrtim_outputs_dropped()) stop_locked();
    }
    fresh |= g_app.evt;
    g_app.evt = 0u;
    __enable_irq();
    if (fresh) console_evt_trip(fresh);
}
