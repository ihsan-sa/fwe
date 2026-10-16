#ifndef FWE_WEBAPP_H
#define FWE_WEBAPP_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "fwe_selftest.h"

/* The phone web app's API: the settings it shows and changes (input, volume, EQ, the sub
 * crossover) and the request handling for GET and POST /api/settings. All of it is pure logic
 * (core/), tested on the host; the HTTP server, the app's page and the NVS writes are the
 * ESP-IDF side's job. Each JSON key is also the setting's NVS key in the `fwe` namespace, so
 * none is over NVS's 15 characters. The self-test route hands its body to fwe_selftest's core. */

#define FWE_WEBAPP_SUBS 2
#define FWE_WEBAPP_MIN_VOLUME_MB (-6000) /* volume, in millibels, up to 0 */
#define FWE_WEBAPP_EQ_RANGE_MB 1200      /* each EQ band, -12 to +12 dB */

typedef enum {
    FWE_INPUT_LMS,     /* squeezelite, from Logitech Media Server */
    FWE_INPUT_AIRPLAY,
    FWE_INPUT_BT,
    FWE_INPUT_SPOTIFY,
    FWE_INPUT_COUNT
} fwe_input_t;

enum { FWE_EQ_BASS, FWE_EQ_MID, FWE_EQ_TREBLE, FWE_EQ_BANDS };

typedef struct {
    fwe_input_t input;
    int32_t volume_mb;
    int32_t eq_mb[FWE_EQ_BANDS];
    uint32_t xover_hz;                          /* FWE_XOVER_MIN_HZ..FWE_XOVER_MAX_HZ */
    int32_t sub_level_mb[FWE_WEBAPP_SUBS];      /* FWE_XOVER_MIN_LEVEL_MB..FWE_XOVER_MAX_LEVEL_MB */
    uint32_t sub_delay_us[FWE_WEBAPP_SUBS];     /* up to FWE_XOVER_MAX_DELAY_US */
} fwe_settings_t;

/* The settings a fresh board starts with: LMS, -20 dB, a flat EQ, an 80 Hz crossover, the subs
 * at 0 dB with no delay. */
void fwe_settings_default(fwe_settings_t *s);

/* Write the settings as one flat JSON object. Returns its length, or -1 when it doesn't fit. */
int fwe_settings_json(const fwe_settings_t *s, char *out, size_t out_len);

/* Apply a flat JSON object of settings to change, e.g. {"volume_mb":-1500,"input":"bt"}. All or
 * nothing: returns 0, or -1 with *err set (a static string) and *s left alone when the body isn't
 * such an object, names a key we don't have, or a value is out of range. */
int fwe_settings_patch(fwe_settings_t *s, const char *body, size_t body_len, const char **err);

/* Handle one API request. GET /api/settings answers the settings; POST /api/settings applies
 * the body and answers the new settings, setting *changed when they differ (the glue then
 * writes NVS and pushes them to the DSP). Returns the HTTP status: 200, 400 with {"error":...}
 * for a bad body, 404 for another path, 405 for another method, or 500 when out_len is too
 * small. */
int fwe_webapp_handle(fwe_settings_t *s, const char *method, const char *path, const char *body,
                      size_t body_len, char *out, size_t out_len, bool *changed);

/* NVS access the glue supplies, one int32 per key in the `fwe` namespace (nvs_get_i32 and
 * nvs_set_i32). Each returns 0, or nonzero when the key is missing or the access fails. */
typedef int (*fwe_nvs_get_fn)(void *ctx, const char *key, int32_t *val);
typedef int (*fwe_nvs_set_fn)(void *ctx, const char *key, int32_t val);

/* Load the settings from NVS: start from the defaults and take each stored key whose value is in
 * the API's range. A missing key, a failed read or an out-of-range value keeps that default, so a
 * stale or corrupt NVS never reaches the DSP. `input` is kept as its fwe_input_t number, so new
 * inputs go at the end. Returns how many keys were taken. */
int fwe_settings_load(fwe_settings_t *s, fwe_nvs_get_fn get, void *ctx);

/* Write each setting that differs from *old, or all of them when old is NULL. Returns 0, or -1 at
 * the first failed write (the glue then doesn't commit). */
int fwe_settings_save(const fwe_settings_t *s, const fwe_settings_t *old, fwe_nvs_set_fn set, void *ctx);

#define FWE_WEBAPP_ST_MAX 63 /* longest st command body POST /api/selftest takes */

/* Handle POST /api/selftest. The body is one npie-selftest/1 command, e.g. `st tone VINL1 1000
 * -20`, run by fwe_selftest_line with the board's ops. Returns the HTTP status: 200 with the
 * console's own answer line (`OK {json}` or `ERR <reason>`, ending in "\n", text/plain) in out,
 * the same line serial and TCP give; 400 with {"error":...} for a body that isn't one st
 * command; 405 for another method; or 500 when out_len is under 32. */
int fwe_webapp_selftest(const fwe_selftest_ops_t *ops, const char *method, const char *body,
                        size_t body_len, char *out, size_t out_len);

#endif
