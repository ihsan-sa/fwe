#ifndef FWE_WEBAPP_H
#define FWE_WEBAPP_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* The phone web app's API: the settings it shows and changes (input, volume, EQ, the sub
 * crossover) and the request handling for GET and POST /api/settings. All of it is pure logic
 * (core/), tested on the host; the HTTP server, the app's page and the NVS writes are the
 * ESP-IDF side's job. Each JSON key is also the setting's NVS key in the `fwe` namespace, so
 * none is over NVS's 15 characters. */

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

#endif
