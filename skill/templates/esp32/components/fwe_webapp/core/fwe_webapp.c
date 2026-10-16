#include "fwe_webapp.h"

#include <stdio.h>
#include <string.h>

#include "fwe_xover.h"

static const char *const INPUTS[FWE_INPUT_COUNT] = {"lms", "airplay", "bt", "spotify"};

/* The integer settings, in the order the JSON lists them. */
enum { F_VOLUME, F_BASS, F_MID, F_TREBLE, F_XOVER, F_SUB1_LEVEL, F_SUB1_DELAY, F_SUB2_LEVEL, F_SUB2_DELAY, F_COUNT };

typedef struct {
    const char *key;
    int32_t min, max;
    const char *err;
} field_t;

static const field_t FIELDS[F_COUNT] = {
    {"volume_mb", FWE_WEBAPP_MIN_VOLUME_MB, 0, "bad volume_mb"},
    {"bass_mb", -FWE_WEBAPP_EQ_RANGE_MB, FWE_WEBAPP_EQ_RANGE_MB, "bad bass_mb"},
    {"mid_mb", -FWE_WEBAPP_EQ_RANGE_MB, FWE_WEBAPP_EQ_RANGE_MB, "bad mid_mb"},
    {"treble_mb", -FWE_WEBAPP_EQ_RANGE_MB, FWE_WEBAPP_EQ_RANGE_MB, "bad treble_mb"},
    {"xover_hz", (int32_t)FWE_XOVER_MIN_HZ, (int32_t)FWE_XOVER_MAX_HZ, "bad xover_hz"},
    {"sub1_level_mb", FWE_XOVER_MIN_LEVEL_MB, FWE_XOVER_MAX_LEVEL_MB, "bad sub1_level_mb"},
    {"sub1_delay_us", 0, (int32_t)FWE_XOVER_MAX_DELAY_US, "bad sub1_delay_us"},
    {"sub2_level_mb", FWE_XOVER_MIN_LEVEL_MB, FWE_XOVER_MAX_LEVEL_MB, "bad sub2_level_mb"},
    {"sub2_delay_us", 0, (int32_t)FWE_XOVER_MAX_DELAY_US, "bad sub2_delay_us"},
};

static int32_t get_field(const fwe_settings_t *s, int f)
{
    switch (f) {
    case F_VOLUME: return s->volume_mb;
    case F_BASS: return s->eq_mb[FWE_EQ_BASS];
    case F_MID: return s->eq_mb[FWE_EQ_MID];
    case F_TREBLE: return s->eq_mb[FWE_EQ_TREBLE];
    case F_XOVER: return (int32_t)s->xover_hz;
    case F_SUB1_LEVEL: return s->sub_level_mb[0];
    case F_SUB1_DELAY: return (int32_t)s->sub_delay_us[0];
    case F_SUB2_LEVEL: return s->sub_level_mb[1];
    default: return (int32_t)s->sub_delay_us[1];
    }
}

static void set_field(fwe_settings_t *s, int f, int32_t v)
{
    switch (f) {
    case F_VOLUME: s->volume_mb = v; break;
    case F_BASS: s->eq_mb[FWE_EQ_BASS] = v; break;
    case F_MID: s->eq_mb[FWE_EQ_MID] = v; break;
    case F_TREBLE: s->eq_mb[FWE_EQ_TREBLE] = v; break;
    case F_XOVER: s->xover_hz = (uint32_t)v; break;
    case F_SUB1_LEVEL: s->sub_level_mb[0] = v; break;
    case F_SUB1_DELAY: s->sub_delay_us[0] = (uint32_t)v; break;
    case F_SUB2_LEVEL: s->sub_level_mb[1] = v; break;
    default: s->sub_delay_us[1] = (uint32_t)v; break;
    }
}

void fwe_settings_default(fwe_settings_t *s)
{
    memset(s, 0, sizeof *s);
    s->input = FWE_INPUT_LMS;
    s->volume_mb = -2000;
    s->xover_hz = 80;
}

int fwe_settings_json(const fwe_settings_t *s, char *out, size_t out_len)
{
    if ((unsigned)s->input >= FWE_INPUT_COUNT) {   /* never index INPUTS with a bad NVS value */
        return -1;
    }
    int n = snprintf(out, out_len, "{\"input\":\"%s\"", INPUTS[s->input]);
    for (int f = 0; f < F_COUNT && n >= 0 && (size_t)n < out_len; f++) {
        n += snprintf(out + n, out_len - (size_t)n, ",\"%s\":%ld", FIELDS[f].key, (long)get_field(s, f));
    }
    if (n >= 0 && (size_t)n < out_len) {
        n += snprintf(out + n, out_len - (size_t)n, "}");
    }
    return (n >= 0 && (size_t)n < out_len) ? n : -1;
}

/* A small reader for the one shape the API takes: a flat object of string and integer values. */
typedef struct {
    const char *p, *end;
} cur_t;

static void skip_ws(cur_t *c)
{
    while (c->p < c->end && (*c->p == ' ' || *c->p == '\t' || *c->p == '\n' || *c->p == '\r')) {
        c->p++;
    }
}

static bool eat(cur_t *c, char ch)
{
    skip_ws(c);
    if (c->p < c->end && *c->p == ch) {
        c->p++;
        return true;
    }
    return false;
}

/* A string with no escapes or control characters, which no key or input name needs. */
static bool read_string(cur_t *c, char *out, size_t len)
{
    if (!eat(c, '"')) {
        return false;
    }
    size_t n = 0;
    while (c->p < c->end && *c->p != '"') {
        unsigned char ch = (unsigned char)*c->p++;
        if (ch < 0x20 || ch == '\\' || n + 1 >= len) {
            return false;
        }
        out[n++] = (char)ch;
    }
    if (c->p >= c->end) {
        return false;
    }
    c->p++;
    out[n] = '\0';
    return true;
}

/* A whole number of at most 9 digits, so it can't overflow an int32. */
static bool read_int(cur_t *c, int32_t *out)
{
    skip_ws(c);
    bool neg = c->p < c->end && *c->p == '-';
    if (neg) {
        c->p++;
    }
    int32_t v = 0;
    int digits = 0;
    while (c->p < c->end && *c->p >= '0' && *c->p <= '9') {
        if (++digits > 9) {
            return false;
        }
        v = v * 10 + (*c->p++ - '0');
    }
    *out = neg ? -v : v;
    return digits > 0;
}

static int find_field(const char *key)
{
    for (int f = 0; f < F_COUNT; f++) {
        if (strcmp(key, FIELDS[f].key) == 0) {
            return f;
        }
    }
    return -1;
}

int fwe_settings_patch(fwe_settings_t *s, const char *body, size_t body_len, const char **err)
{
    cur_t c = {body, body + body_len};
    fwe_settings_t t = *s;
    char key[32], name[16];
    *err = "bad json";
    if (body == NULL || !eat(&c, '{')) {
        return -1;
    }
    if (!eat(&c, '}')) {
        do {
            if (!read_string(&c, key, sizeof key) || !eat(&c, ':')) {
                return -1;
            }
            if (strcmp(key, "input") == 0) {
                int i = 0;
                if (read_string(&c, name, sizeof name)) {
                    while (i < FWE_INPUT_COUNT && strcmp(name, INPUTS[i]) != 0) {
                        i++;
                    }
                } else {
                    i = FWE_INPUT_COUNT;
                }
                if (i == FWE_INPUT_COUNT) {
                    *err = "bad input";
                    return -1;
                }
                t.input = (fwe_input_t)i;
                continue;
            }
            int f = find_field(key);
            if (f < 0) {
                *err = "unknown key";
                return -1;
            }
            int32_t v;
            if (!read_int(&c, &v) || v < FIELDS[f].min || v > FIELDS[f].max) {
                *err = FIELDS[f].err;
                return -1;
            }
            set_field(&t, f, v);
        } while (eat(&c, ','));
        if (!eat(&c, '}')) {
            return -1;
        }
    }
    skip_ws(&c);
    if (c.p != c.end) {
        return -1;
    }
    *s = t;
    *err = NULL;
    return 0;
}

static bool settings_equal(const fwe_settings_t *a, const fwe_settings_t *b)
{
    if (a->input != b->input) {
        return false;
    }
    for (int f = 0; f < F_COUNT; f++) {
        if (get_field(a, f) != get_field(b, f)) {
            return false;
        }
    }
    return true;
}

int fwe_settings_load(fwe_settings_t *s, fwe_nvs_get_fn get, void *ctx)
{
    int taken = 0;
    int32_t v;
    fwe_settings_default(s);
    if (get(ctx, "input", &v) == 0 && v >= 0 && v < FWE_INPUT_COUNT) {
        s->input = (fwe_input_t)v;
        taken++;
    }
    for (int f = 0; f < F_COUNT; f++) {
        if (get(ctx, FIELDS[f].key, &v) == 0 && v >= FIELDS[f].min && v <= FIELDS[f].max) {
            set_field(s, f, v);
            taken++;
        }
    }
    return taken;
}

int fwe_settings_save(const fwe_settings_t *s, const fwe_settings_t *old, fwe_nvs_set_fn set, void *ctx)
{
    if ((old == NULL || old->input != s->input) && set(ctx, "input", (int32_t)s->input) != 0) {
        return -1;
    }
    for (int f = 0; f < F_COUNT; f++) {
        int32_t v = get_field(s, f);
        if ((old == NULL || get_field(old, f) != v) && set(ctx, FIELDS[f].key, v) != 0) {
            return -1;
        }
    }
    return 0;
}

static int answer_error(char *out, size_t out_len, int status, const char *msg)
{
    int n = snprintf(out, out_len, "{\"error\":\"%s\"}", msg);
    return (n >= 0 && (size_t)n < out_len) ? status : 500;
}

int fwe_webapp_handle(fwe_settings_t *s, const char *method, const char *path, const char *body,
                      size_t body_len, char *out, size_t out_len, bool *changed)
{
    *changed = false;
    if (strcmp(path, "/api/settings") != 0) {
        return answer_error(out, out_len, 404, "not found");
    }
    if (strcmp(method, "POST") == 0) {
        fwe_settings_t before = *s;
        const char *err;
        if (fwe_settings_patch(s, body, body_len, &err) != 0) {
            return answer_error(out, out_len, 400, err);
        }
        *changed = !settings_equal(&before, s);
    } else if (strcmp(method, "GET") != 0) {
        return answer_error(out, out_len, 405, "method not allowed");
    }
    return fwe_settings_json(s, out, out_len) < 0 ? 500 : 200;
}

int fwe_webapp_selftest(const fwe_selftest_ops_t *ops, const char *method, const char *body,
                        size_t body_len, char *out, size_t out_len)
{
    char line[FWE_WEBAPP_ST_MAX + 1];
    if (out_len < 32) {
        return 500;
    }
    if (strcmp(method, "POST") != 0) {
        return answer_error(out, out_len, 405, "method not allowed");
    }
    if (body_len > FWE_WEBAPP_ST_MAX) {
        return answer_error(out, out_len, 400, "body too long");
    }
    if (body_len && memchr(body, '\0', body_len)) {
        return answer_error(out, out_len, 400, "not an st command");
    }
    if (body_len) {
        memcpy(line, body, body_len);
    }
    line[body_len] = '\0';
    if (fwe_selftest_line(ops, line, out, out_len) == 0) {
        return answer_error(out, out_len, 400, "not an st command");
    }
    return 200;
}
