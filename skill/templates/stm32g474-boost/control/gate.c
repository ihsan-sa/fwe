#include "gate.h"

void gate_init(gate_t *g)
{
    g->st = GATE_OFF;
}

gate_act_t gate_update(gate_t *g, int armed, int faulted, uint32_t cmp1, int loaded)
{
    if (!armed || faulted || cmp1 == 0u) {
        g->st = GATE_OFF;
        return GATE_ACT_DISABLE;
    }
    if (g->st == GATE_OFF) {
        g->st = GATE_PENDING; /* the pulse is in the preload; outputs stay off */
        return GATE_ACT_NONE;
    }
    /* PENDING means the previous compare was non-zero too, so once it is
     * loaded the active register holds a real pulse */
    if (g->st == GATE_PENDING && loaded) {
        g->st = GATE_PWM;
        return GATE_ACT_ENABLE;
    }
    return GATE_ACT_NONE;
}

int gate_outputs_wanted(const gate_t *g)
{
    return g->st == GATE_PWM;
}
