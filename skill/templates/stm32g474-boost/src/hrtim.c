/* hrtim.c - HRTIM1 Timer A drives the LMG2100 half-bridge (RM0440 chapter 28).
 *
 * TA1 = PWM_LO = the main (low-side) switch: set on the period event, reset
 * on CMP1, so it is on for D. TA2 = PWM_HI is TA1's complement from the
 * dead-time unit (OUTR.DTEN), DEADTIME_NS on both edges. Outputs are
 * active-high; idle and fault states are inactive, so a disabled or faulted
 * timer holds both GaN switches off.
 *
 * Clock: fHRTIM = 170 MHz, CKPSC = 0, so the counter runs at fHRTIM x 32
 * through the DLL (28.3.3) and PER = 5440 for 1 MHz (computed, scale.c).
 * Dead time: tDTG = 2^DTPRSC x tHRTIM / 8 (28.3.4, Table 237); DTPRSC = 0
 * gives 0.735 ns steps, so 10 ns is 14 steps = 10.29 ns (rounded up).
 * Duty: CMP1 and the ADC trigger compare CMP2 are preloaded and move at the
 * repetition event (REP = 0: every period), so a new duty never cuts a pulse.
 *
 * Faults (28.3.17): the board's comparators reach FLTn on-chip (FLTxSRC =
 * 01, Table 228; the pin map verified which FLT each COMP reaches), active
 * high, enabled on Timer A. A fault drops the outputs to their fault state
 * and clears TxyOEN in hardware; firmware only learns of it from the ISR
 * flags.
 *
 * ADC trigger 2 (hrtim_adc_trg2 -> ADC1 JEXTSEL 10011, RM0440 Table 167) on
 * Timer A CMP2, mid on-time; post-scaled by CTRL_DIV (ADCPS1.AD2PSC, 28.3.20). */
#include "app.h"
#include "scale.h"

#define TA (HRTIM1->sTimerxRegs[0])
#define HC (HRTIM1->sCommonRegs)

static uint32_t s_per;

static GPIO_TypeDef *const k_gate_port[2] = { PIN_PWM_LO_PORT, PIN_PWM_HI_PORT };
static const uint32_t k_gate_pin[2] = { PIN_PWM_LO_PIN, PIN_PWM_HI_PIN };
static const uint32_t k_gate_af[2] = { PIN_PWM_LO_AF, PIN_PWM_HI_AF };

void hrtim_gate_pins_safe(void)
{
    for (int k = 0; k < 2; k++) {
        gpio_write(k_gate_port[k], k_gate_pin[k], 0);
        gpio_mode(k_gate_port[k], k_gate_pin[k], GPIO_OUT);
        k_gate_port[k]->PUPDR = (k_gate_port[k]->PUPDR & ~(3u << (k_gate_pin[k] * 2u)))
                              | (2u << (k_gate_pin[k] * 2u)); /* pull-down: low in every mode */
    }
}

void hrtim_gate_pins_af(void)
{
    for (int k = 0; k < 2; k++) {
        k_gate_port[k]->OSPEEDR |= 3u << (k_gate_pin[k] * 2u); /* very high: sub-ns edges */
        gpio_af(k_gate_port[k], k_gate_pin[k], k_gate_af[k]);
        gpio_mode(k_gate_port[k], k_gate_pin[k], GPIO_AF);
    }
}

/* FLTn configuration: on-chip source (FLTxSRC = 01), active high, the
 * FAULT_FILTER digital filter, and its FLTn enable on a timer. */
typedef struct {
    volatile uint32_t *inr;   /* FLTINR1 (FLT1..4) or FLTINR2 (FLT5..6) */
    uint32_t cfg, en, src1;   /* P|SRC0|F, E, SRC[1] (in FLTINR2) */
    uint32_t timer_en, isr, icr; /* FLTxR.FLTnEN, ISR.FLTn, ICR.FLTnC */
} flt_t;

static int flt_of(uint32_t n, flt_t *f)
{
    switch (n) {
    case 1u: *f = (flt_t){ &HC.FLTINR1, HRTIM_FLTINR1_FLT1P | HRTIM_FLTINR1_FLT1SRC_0 | (FAULT_FILTER << HRTIM_FLTINR1_FLT1F_Pos),
                           HRTIM_FLTINR1_FLT1E, HRTIM_FLTINR2_FLT1SRC_1, HRTIM_FLTR_FLT1EN, HRTIM_ISR_FLT1, HRTIM_ICR_FLT1C }; return 0;
    case 2u: *f = (flt_t){ &HC.FLTINR1, HRTIM_FLTINR1_FLT2P | HRTIM_FLTINR1_FLT2SRC_0 | (FAULT_FILTER << HRTIM_FLTINR1_FLT2F_Pos),
                           HRTIM_FLTINR1_FLT2E, HRTIM_FLTINR2_FLT2SRC_1, HRTIM_FLTR_FLT2EN, HRTIM_ISR_FLT2, HRTIM_ICR_FLT2C }; return 0;
    case 3u: *f = (flt_t){ &HC.FLTINR1, HRTIM_FLTINR1_FLT3P | HRTIM_FLTINR1_FLT3SRC_0 | (FAULT_FILTER << HRTIM_FLTINR1_FLT3F_Pos),
                           HRTIM_FLTINR1_FLT3E, HRTIM_FLTINR2_FLT3SRC_1, HRTIM_FLTR_FLT3EN, HRTIM_ISR_FLT3, HRTIM_ICR_FLT3C }; return 0;
    case 4u: *f = (flt_t){ &HC.FLTINR1, HRTIM_FLTINR1_FLT4P | HRTIM_FLTINR1_FLT4SRC_0 | (FAULT_FILTER << HRTIM_FLTINR1_FLT4F_Pos),
                           HRTIM_FLTINR1_FLT4E, HRTIM_FLTINR2_FLT4SRC_1, HRTIM_FLTR_FLT4EN, HRTIM_ISR_FLT4, HRTIM_ICR_FLT4C }; return 0;
    case 5u: *f = (flt_t){ &HC.FLTINR2, HRTIM_FLTINR2_FLT5P | HRTIM_FLTINR2_FLT5SRC_0 | (FAULT_FILTER << HRTIM_FLTINR2_FLT5F_Pos),
                           HRTIM_FLTINR2_FLT5E, HRTIM_FLTINR2_FLT5SRC_1, HRTIM_FLTR_FLT5EN, HRTIM_ISR_FLT5, HRTIM_ICR_FLT5C }; return 0;
    case 6u: *f = (flt_t){ &HC.FLTINR2, HRTIM_FLTINR2_FLT6P | HRTIM_FLTINR2_FLT6SRC_0 | (FAULT_FILTER << HRTIM_FLTINR2_FLT6F_Pos),
                           HRTIM_FLTINR2_FLT6E, HRTIM_FLTINR2_FLT6SRC_1, HRTIM_FLTR_FLT6EN, HRTIM_ISR_FLT6, HRTIM_ICR_FLT6C }; return 0;
    default: return -1;
    }
}

static int fault_input_init(uint32_t n)
{
    flt_t f;
    if (flt_of(n, &f)) return -1;
    HC.FLTINR2 &= ~f.src1;              /* FLTxSRC[1] = 0 ...           */
    *f.inr |= f.cfg;                    /* ... [0] = 1: on-chip (COMP)  */
    *f.inr |= f.en;                     /* enable after source and polarity */
    TA.FLTxR |= f.timer_en;
    return 0;
}

int hrtim_dll_ready(void)
{
    return (HC.ISR & HRTIM_ISR_DLLRDY) != 0u;
}

int hrtim_init(void)
{
    RCC->APB2ENR |= RCC_APB2ENR_HRTIM1EN;
    (void)RCC->APB2ENR;
    DBGMCU->APB2FZ |= DBGMCU_APB2FZ_DBG_HRTIM1_STOP; /* a halted core freezes the PWM */

    /* 28.3.24: calibrate the DLL first, then keep it calibrated periodically */
    HC.DLLCR = HRTIM_DLLCR_CAL;
    uint32_t n = 0;
    while (!hrtim_dll_ready())
        if (++n > 1000000u) return -1;
    HC.DLLCR = HRTIM_DLLCR_CALEN | (3u << HRTIM_DLLCR_CALRTE_Pos); /* CALRTE 11: every 2048 tHRTIM = 12 us */

    s_per = hr_period(HRTIM_FHRTIM_HZ, PWM_FREQ_HZ, 0u);
    if (s_per < HR_CMP_MIN || s_per > 0xFFDFu) return -2; /* 28.5.17: PER range at CKPSC = 0 */
    uint32_t dt = hr_deadtime(DEADTIME_NS, HRTIM_FHRTIM_HZ, 0u);

    HC.ODISR = HRTIM_ODISR_TA1ODIS | HRTIM_ODISR_TA2ODIS;
    TA.TIMxCR = HRTIM_TIMCR_CONT | HRTIM_TIMCR_PREEN | HRTIM_TIMCR_TREPU; /* CKPSC = 0 */
    TA.PERxR = s_per;
    TA.REPxR = 0u;
    TA.CMP1xR = 0u;                                    /* null duty: no pulse */
    TA.CMP2xR = hr_adc_cmp(0u, s_per);
    TA.DTxR = (dt << HRTIM_DTR_DTR_Pos) | (dt << HRTIM_DTR_DTF_Pos); /* DTPRSC = 0, both positive */
    TA.SETx1R = HRTIM_SET1R_PER;
    TA.RSTx1R = HRTIM_RST1R_CMP1;
    TA.SETx2R = 0u;                                    /* TA2 comes from the dead-time unit */
    TA.RSTx2R = 0u;
    /* POL = 0 (active high), IDLES = 0 (inactive), FAULT = 10 (inactive) */
    TA.OUTxR = HRTIM_OUTR_DTEN | HRTIM_OUTR_FAULT1_1 | HRTIM_OUTR_FAULT2_1;

    /* ADC trigger 2 on Timer A CMP2, loaded on Timer A's update, every CTRL_DIV periods */
    HC.CR1 = (HC.CR1 & ~HRTIM_CR1_ADC2USRC) | HRTIM_CR1_ADC2USRC_0;   /* 001: Timer A */
    HC.ADC2R = HRTIM_ADC2R_AD2TAC2;
    HC.ADCPS1 = (HC.ADCPS1 & ~HRTIM_ADCPS1_AD2PSC) | ((CTRL_DIV - 1u) << HRTIM_ADCPS1_AD2PSC_Pos);

    /* 28.3.24 note: with DTEN, force the output state by software before RUN */
    TA.RSTx1R |= HRTIM_RST1R_SRT;
    TA.RSTx1R = HRTIM_RST1R_CMP1;

    HRTIM1->sMasterRegs.MCR |= HRTIM_MCR_TACEN;        /* counting; outputs still disabled */
    return 0;
}

int hrtim_faults_init(void)
{
    if (fault_input_init(TRIP_OVP_FLT) || fault_input_init(TRIP_OCP_FLT)) return -1;
    hrtim_fault_flags_clear();
    return 0;
}

uint32_t hrtim_period(void)
{
    return s_per;
}

void hrtim_set_duty(float d)
{
    uint32_t c = hr_duty_cmp(d, D_MAX, s_per);
    TA.CMP1xR = c;
    TA.CMP2xR = hr_adc_cmp(c, s_per);
    g_app.duty = (float)c / (float)s_per;
}

void hrtim_outputs_on(void)
{
    HC.OENR = HRTIM_OENR_TA1OEN | HRTIM_OENR_TA2OEN; /* refused by hardware while a fault is active */
}

void hrtim_outputs_off(void)
{
    HC.ODISR = HRTIM_ODISR_TA1ODIS | HRTIM_ODISR_TA2ODIS;
    TA.CMP1xR = 0u;
    g_app.duty = 0.0f;
}

int hrtim_outputs_are_on(void)
{
    return (HC.OENR & (HRTIM_OENR_TA1OEN | HRTIM_OENR_TA2OEN)) != 0u;
}

uint32_t hrtim_fault_flags(void)
{
    flt_t ov, oc;
    uint32_t isr = HC.ISR, out = 0u;
    if (!flt_of(TRIP_OVP_FLT, &ov) && (isr & ov.isr)) out |= TRIP_OVP_HW;
    if (!flt_of(TRIP_OCP_FLT, &oc) && (isr & oc.isr)) out |= TRIP_OCP_HW;
    return out;
}

void hrtim_fault_flags_clear(void)
{
    flt_t ov, oc;
    uint32_t m = 0u;
    if (!flt_of(TRIP_OVP_FLT, &ov)) m |= ov.icr;
    if (!flt_of(TRIP_OCP_FLT, &oc)) m |= oc.icr;
    HC.ICR = m;
}
