#include "sixstep.h"

static const int8_t hall_to_step[8] = { -1, 0, 2, 1, 4, 5, 3, -1 };

static const sixstep_drive_t step_drive[6] = {
    { +1, -1, 0 }, { +1, 0, -1 }, { 0, +1, -1 },
    { -1, +1, 0 }, { -1, 0, +1 }, { 0, -1, +1 },
};

int sixstep_step(uint8_t hall)
{
    return hall < 8u ? hall_to_step[hall] : -1;
}

int sixstep_drive(uint8_t hall, int reverse, sixstep_drive_t *out)
{
    int k = sixstep_step(hall);
    if (k < 0) {
        out->a = out->b = out->c = 0;
        return -1;
    }
    *out = step_drive[k];
    if (reverse) {
        out->a = (int8_t)-out->a;
        out->b = (int8_t)-out->b;
        out->c = (int8_t)-out->c;
    }
    return 0;
}
