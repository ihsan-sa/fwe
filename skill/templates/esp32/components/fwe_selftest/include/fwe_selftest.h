#ifndef FWE_SELFTEST_H
#define FWE_SELFTEST_H

#include <stddef.h>
#include <stdint.h>

/* The self-test console /npie drives in bring-up (npie-selftest/1): `st rails`, `st pd`,
 * `st tone <tap> <hz> <dBFS>` and `st net`, each answered by one line, `OK {json}` or
 * `ERR <reason>`, the same over USB serial and over TCP. core/ reads the line, checks the
 * arguments and frames the answer; the measuring is the board's handlers', which the ESP-IDF
 * glue supplies. The JSON each handler writes is npie-selftest/1's, not decided here. */

#define FWE_ST_TONE_MIN_HZ 20
#define FWE_ST_TONE_MAX_HZ 20000
#define FWE_ST_TONE_MIN_DBFS (-60.0)
#define FWE_ST_TAP_MAX 15 /* longest tap name, the PCM1863 mux input the tone is read back on */

typedef struct {
    char tap[FWE_ST_TAP_MAX + 1];
    unsigned hz;
    double dbfs;
} fwe_st_tone_t;

/* Each handler writes one JSON object (no newline) into out and returns its length, or returns
 * -1 with *err set to a static one-line reason, e.g. "no PD contract" or "unknown tap". A NULL
 * handler answers `ERR not supported`. */
typedef int (*fwe_st_fn)(void *ctx, char *out, size_t out_len, const char **err);
typedef int (*fwe_st_tone_fn)(void *ctx, const fwe_st_tone_t *tone, char *out, size_t out_len,
                              const char **err);

typedef struct {
    fwe_st_fn rails;
    fwe_st_fn pd;
    fwe_st_tone_fn tone;
    fwe_st_fn net;
    void *ctx;
} fwe_selftest_ops_t;

/* Answer one console line (its trailing \r\n, if any, ignored). Writes the answer line, ending
 * in "\n", into out and returns its length. Returns 0, writing nothing, for a line that isn't an
 * `st` command (blank, or another console's), so the glue can pass it on. An answer that doesn't
 * fit, or a handler's JSON that isn't one object on one line, is `ERR` too; out_len must be at
 * least 32. */
int fwe_selftest_line(const fwe_selftest_ops_t *ops, const char *line, char *out, size_t out_len);

/* The PCM1863's analog mux, which `st tone` sets to read the tone back on a tap. Page 0's
 * ADC1_INPUT_SEL_L picks one of VINL1-4 and ADC1_INPUT_SEL_R one of VINR1-4, single-ended, one
 * bit each (bit n-1 for input n), over the register's default upper bits (0x40). From memory
 * of the PCM186x register map, not yet checked against SLAS831, as the pin names aren't. */
#define FWE_PCM1863_REG_ADC1_SEL_L 0x06
#define FWE_PCM1863_REG_ADC1_SEL_R 0x07
#define FWE_PCM1863_SEL_BASE 0x40

/* The register and value that select tap ("VINL1" to "VINR4", as the manifest's taps name them).
 * Returns 0, or -1 for a tap that isn't one of the eight, so the handler answers `ERR unknown tap`. */
int fwe_st_pcm1863_mux(const char *tap, uint8_t *reg, uint8_t *val);

/* The tone `st tone` plays and the level it reads back, on 32-bit I2S samples (full scale
 * INT32_MAX, so a full-scale sine is 0 dBFS). Neither needs the DAC or the ADC: the glue fills
 * the DAC's DMA buffers and hands the PCM1863's capture to the level. */
#define FWE_ST_TONE_FLOOR_DBFS (-150.0) /* the level of silence, so the answer's JSON stays a number */

/* n mono samples of a hz sine at dbfs, from sample number start, so the glue can fill one DMA
 * buffer after another and the tone stays continuous. */
void fwe_st_tone_fill(int32_t *buf, size_t n, uint64_t start, unsigned rate_hz, unsigned hz, double dbfs);

/* The level in dBFS of the hz component of n mono samples (a Hann window and a Goertzel at hz
 * exactly, not at the nearest bin), so other tones, hum and DC barely move it. Never below
 * FWE_ST_TONE_FLOOR_DBFS; n == 0 reads as silence. */
double fwe_st_tone_level(const int32_t *buf, size_t n, unsigned rate_hz, unsigned hz);

#endif
