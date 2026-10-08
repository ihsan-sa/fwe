/* hrtim_stub.h - a host stand-in for app.h, so test_hrtim_arm.c can compile
 * src/hrtim.c itself against plain-memory registers. Bit values are copied
 * from the pinned cmsis-device-g4 v1.2.6 stm32g474xx.h; the register blocks
 * hold only the fields hrtim.c touches. Plain memory does not act like the
 * HRTIM (OENR/ODISR set and clear, ICR clears ISR, CMP1 preloads): the test
 * applies those effects itself after each call (see hw_settle()). */
#ifndef HRTIM_STUB_H
#define HRTIM_STUB_H

#define APP_H /* src/hrtim.c's #include "app.h" is then empty */

#include <stdint.h>
#include "board_pins.h"
#include "fw_config.h"
#include "trip.h"

#define DBGMCU_APB2FZ_DBG_HRTIM1_STOP    0x04000000u
#define HRTIM_ADC2R_AD2TAC2              0x00000400u
#define HRTIM_ADCPS1_AD2PSC              0x000007C0u
#define HRTIM_ADCPS1_AD2PSC_Pos          0x00000006u
#define HRTIM_CR1_ADC2USRC               0x00380000u
#define HRTIM_CR1_ADC2USRC_0             0x00080000u
#define HRTIM_DLLCR_CAL                  0x00000001u
#define HRTIM_DLLCR_CALEN                0x00000002u
#define HRTIM_DLLCR_CALRTE_Pos           0x00000002u
#define HRTIM_DTR_DTF_Pos                0x00000010u
#define HRTIM_DTR_DTR_Pos                0x00000000u
#define HRTIM_FLTINR1_FLT1E              0x00000001u
#define HRTIM_FLTINR1_FLT1F_Pos          0x00000003u
#define HRTIM_FLTINR1_FLT1LCK            0x00000080u
#define HRTIM_FLTINR1_FLT1P              0x00000002u
#define HRTIM_FLTINR1_FLT1SRC_0          0x00000004u
#define HRTIM_FLTINR1_FLT2E              0x00000100u
#define HRTIM_FLTINR1_FLT2F_Pos          0x0000000Bu
#define HRTIM_FLTINR1_FLT2LCK            0x00008000u
#define HRTIM_FLTINR1_FLT2P              0x00000200u
#define HRTIM_FLTINR1_FLT2SRC_0          0x00000400u
#define HRTIM_FLTINR1_FLT3E              0x00010000u
#define HRTIM_FLTINR1_FLT3F_Pos          0x00000013u
#define HRTIM_FLTINR1_FLT3LCK            0x00800000u
#define HRTIM_FLTINR1_FLT3P              0x00020000u
#define HRTIM_FLTINR1_FLT3SRC_0          0x00040000u
#define HRTIM_FLTINR1_FLT4E              0x01000000u
#define HRTIM_FLTINR1_FLT4F_Pos          0x0000001Bu
#define HRTIM_FLTINR1_FLT4LCK            0x80000000u
#define HRTIM_FLTINR1_FLT4P              0x02000000u
#define HRTIM_FLTINR1_FLT4SRC_0          0x04000000u
#define HRTIM_FLTINR2_FLT1SRC_1          0x00010000u
#define HRTIM_FLTINR2_FLT2SRC_1          0x00020000u
#define HRTIM_FLTINR2_FLT3SRC_1          0x00040000u
#define HRTIM_FLTINR2_FLT4SRC_1          0x00080000u
#define HRTIM_FLTINR2_FLT5E              0x00000001u
#define HRTIM_FLTINR2_FLT5F_Pos          0x00000003u
#define HRTIM_FLTINR2_FLT5LCK            0x00000080u
#define HRTIM_FLTINR2_FLT5P              0x00000002u
#define HRTIM_FLTINR2_FLT5SRC_0          0x00000004u
#define HRTIM_FLTINR2_FLT5SRC_1          0x00100000u
#define HRTIM_FLTINR2_FLT6E              0x00000100u
#define HRTIM_FLTINR2_FLT6F_Pos          0x0000000Bu
#define HRTIM_FLTINR2_FLT6LCK            0x00008000u
#define HRTIM_FLTINR2_FLT6P              0x00000200u
#define HRTIM_FLTINR2_FLT6SRC_0          0x00000400u
#define HRTIM_FLTINR2_FLT6SRC_1          0x00200000u
#define HRTIM_FLTR_FLT1EN                0x00000001u
#define HRTIM_FLTR_FLT2EN                0x00000002u
#define HRTIM_FLTR_FLT3EN                0x00000004u
#define HRTIM_FLTR_FLT4EN                0x00000008u
#define HRTIM_FLTR_FLT5EN                0x00000010u
#define HRTIM_FLTR_FLT6EN                0x00000020u
#define HRTIM_FLTR_FLTLCK                0x80000000u
#define HRTIM_ICR_FLT1C                  0x00000001u
#define HRTIM_ICR_FLT2C                  0x00000002u
#define HRTIM_ICR_FLT3C                  0x00000004u
#define HRTIM_ICR_FLT4C                  0x00000008u
#define HRTIM_ICR_FLT5C                  0x00000010u
#define HRTIM_ICR_FLT6C                  0x00000040u
#define HRTIM_ISR_DLLRDY                 0x00010000u
#define HRTIM_ISR_FLT1                   0x00000001u
#define HRTIM_ISR_FLT2                   0x00000002u
#define HRTIM_ISR_FLT3                   0x00000004u
#define HRTIM_ISR_FLT4                   0x00000008u
#define HRTIM_ISR_FLT5                   0x00000010u
#define HRTIM_ISR_FLT6                   0x00000040u
#define HRTIM_MCR_TACEN                  0x00020000u
#define HRTIM_ODISR_TA1ODIS              0x00000001u
#define HRTIM_ODISR_TA2ODIS              0x00000002u
#define HRTIM_OENR_TA1OEN                0x00000001u
#define HRTIM_OENR_TA2OEN                0x00000002u
#define HRTIM_OUTR_DTEN                  0x00000100u
#define HRTIM_OUTR_FAULT1_1              0x00000020u
#define HRTIM_OUTR_FAULT2_1              0x00200000u
#define HRTIM_RST1R_CMP1                 0x00000008u
#define HRTIM_RST1R_SRT                  0x00000001u
#define HRTIM_SET1R_PER                  0x00000004u
#define HRTIM_TIMCR_CONT                 0x00000008u
#define HRTIM_TIMCR_PREEN                0x08000000u
#define HRTIM_TIMCR_TREPU                0x00020000u
#define HRTIM_TIMICR_REPC                0x00000010u
#define HRTIM_TIMISR_REP                 0x00000010u
#define RCC_APB2ENR_HRTIM1EN             0x04000000u

typedef struct {
    volatile uint32_t TIMxCR, TIMxISR, TIMxICR, PERxR, REPxR, CMP1xR, CMP2xR, DTxR;
    volatile uint32_t SETx1R, RSTx1R, SETx2R, RSTx2R, OUTxR, FLTxR;
} HRTIM_Timerx_TypeDef;
typedef struct {
    volatile uint32_t CR1, ISR, ICR, OENR, ODISR, DLLCR, FLTINR1, FLTINR2, ADC2R, ADCPS1;
} HRTIM_Common_TypeDef;
typedef struct { volatile uint32_t MCR; } HRTIM_Master_TypeDef;
typedef struct {
    HRTIM_Master_TypeDef sMasterRegs;
    HRTIM_Timerx_TypeDef sTimerxRegs[6];
    HRTIM_Common_TypeDef sCommonRegs;
} HRTIM_TypeDef;
typedef struct { volatile uint32_t PUPDR, OSPEEDR; } GPIO_TypeDef;
typedef struct { volatile uint32_t APB2ENR; } RCC_TypeDef;
typedef struct { volatile uint32_t APB2FZ; } DBGMCU_TypeDef;

static HRTIM_TypeDef fake_hrtim;
static GPIO_TypeDef fake_gpio;
static RCC_TypeDef fake_rcc;
static DBGMCU_TypeDef fake_dbgmcu;
#define HRTIM1 (&fake_hrtim)
#define GPIOA (&fake_gpio) /* HRTIM1 TA1/TA2 are PA8/PA9 only */
#define RCC (&fake_rcc)
#define DBGMCU (&fake_dbgmcu)

enum { GPIO_IN = 0u, GPIO_OUT = 1u, GPIO_AF = 2u, GPIO_ANALOG = 3u };
static void gpio_mode(GPIO_TypeDef *g, uint32_t pin, uint32_t mode) { (void)g; (void)pin; (void)mode; }
static void gpio_af(GPIO_TypeDef *g, uint32_t pin, uint32_t af) { (void)g; (void)pin; (void)af; }
static void gpio_write(GPIO_TypeDef *g, uint32_t pin, int on) { (void)g; (void)pin; (void)on; }

static struct { float duty; } g_app;

/* app.h's prototypes that hrtim.c calls before it defines them */
uint32_t hrtim_fault_flags(void);
void hrtim_fault_flags_clear(void);

#endif
