#include "fwe_selftest.h"

#include <math.h>

#define PI_D 3.14159265358979323846

void fwe_st_tone_fill(int32_t *buf, size_t n, uint64_t start, unsigned rate_hz, unsigned hz, double dbfs)
{
    double amp = (double)INT32_MAX * pow(10.0, dbfs / 20.0);
    double w = 2.0 * PI_D * hz / rate_hz;
    /* the phase from (start + i) mod rate, so a long tone keeps its precision */
    for (size_t i = 0; i < n; i++) {
        uint64_t k = (start + i) % rate_hz;
        double s = amp * sin(w * (double)k);
        if (s > INT32_MAX) s = INT32_MAX;
        if (s < -(double)INT32_MAX) s = -(double)INT32_MAX;
        buf[i] = (int32_t)lrint(s);
    }
}

double fwe_st_tone_level(const int32_t *buf, size_t n, unsigned rate_hz, unsigned hz)
{
    if (n == 0 || rate_hz == 0) return FWE_ST_TONE_FLOOR_DBFS;
    double w = 2.0 * PI_D * hz / rate_hz;
    double coeff = 2.0 * cos(w);
    double s1 = 0.0, s2 = 0.0, wsum = 0.0;
    for (size_t i = 0; i < n; i++) {
        double win = 0.5 - 0.5 * cos(2.0 * PI_D * (double)i / (double)n); /* periodic Hann */
        double s0 = win * buf[i] + coeff * s1 - s2;
        s2 = s1;
        s1 = s0;
        wsum += win;
    }
    double mag2 = s1 * s1 + s2 * s2 - coeff * s1 * s2;
    if (!(mag2 > 0.0) || wsum <= 0.0) return FWE_ST_TONE_FLOOR_DBFS;
    double amp = 2.0 * sqrt(mag2) / wsum; /* the sine's peak, in counts */
    double db = 20.0 * log10(amp / (double)INT32_MAX);
    return db < FWE_ST_TONE_FLOOR_DBFS ? FWE_ST_TONE_FLOOR_DBFS : db;
}
