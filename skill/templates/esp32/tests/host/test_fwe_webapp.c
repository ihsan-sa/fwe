#include <assert.h>
#include <stdio.h>
#include <string.h>

#include "fwe_webapp.h"

static int fake_rails(void *ctx, char *out, size_t len, const char **err)
{
    (void)ctx;
    (void)err;
    return snprintf(out, len, "{\"vbus_mv\":20000}");
}

static int fake_tone(void *ctx, const fwe_st_tone_t *tone, char *out, size_t len, const char **err)
{
    *(fwe_st_tone_t *)ctx = *tone;
    (void)err;
    return snprintf(out, len, "{\"thd_pct\":0.01}");
}

#define DEFAULTS "{\"input\":\"lms\",\"volume_mb\":-2000,\"bass_mb\":0,\"mid_mb\":0,\"treble_mb\":0," \
                 "\"xover_hz\":80,\"sub1_level_mb\":0,\"sub1_delay_us\":0,\"sub2_level_mb\":0,\"sub2_delay_us\":0}"

static int post(fwe_settings_t *s, const char *body, char *out, size_t len, bool *changed)
{
    return fwe_webapp_handle(s, "POST", "/api/settings", body, strlen(body), out, len, changed);
}

static void test_get_answers_the_defaults(void)
{
    fwe_settings_t s;
    char out[512];
    bool changed = true;
    fwe_settings_default(&s);
    assert(fwe_webapp_handle(&s, "GET", "/api/settings", NULL, 0, out, sizeof out, &changed) == 200);
    assert(strcmp(out, DEFAULTS) == 0 && !changed);
}

static void test_post_changes_only_what_it_names(void)
{
    fwe_settings_t s;
    char out[512];
    bool changed = false;
    fwe_settings_default(&s);
    assert(post(&s, " { \"input\" : \"bt\", \"volume_mb\":-1500,\n\"sub2_delay_us\":20000,"
                    "\"xover_hz\":120 } ", out, sizeof out, &changed) == 200);
    assert(changed);
    assert(s.input == FWE_INPUT_BT && s.volume_mb == -1500 && s.xover_hz == 120);
    assert(s.sub_delay_us[1] == 20000 && s.sub_delay_us[0] == 0 && s.sub_level_mb[1] == 0);
    assert(strstr(out, "\"input\":\"bt\"") && strstr(out, "\"sub2_delay_us\":20000}"));
    /* the same values again change nothing, and an empty object is a no-op */
    assert(post(&s, "{\"volume_mb\":-1500}", out, sizeof out, &changed) == 200 && !changed);
    assert(post(&s, "{}", out, sizeof out, &changed) == 200 && !changed);
    /* the range ends are in */
    assert(post(&s, "{\"bass_mb\":-1200,\"treble_mb\":1200,\"sub1_level_mb\":-6000,\"sub2_level_mb\":1200,"
                    "\"xover_hz\":40,\"volume_mb\":0,\"input\":\"spotify\"}", out, sizeof out, &changed) == 200);
    assert(s.eq_mb[FWE_EQ_BASS] == -1200 && s.eq_mb[FWE_EQ_TREBLE] == 1200 && s.xover_hz == 40);
    assert(s.sub_level_mb[0] == -6000 && s.sub_level_mb[1] == 1200 && s.input == FWE_INPUT_SPOTIFY);
}

/* A bad body answers 400 with the reason, and changes nothing, not even the keys before the bad one. */
static void expect_400(const char *body, const char *reason)
{
    fwe_settings_t s;
    char out[512], want[64];
    bool changed = true;
    fwe_settings_default(&s);
    assert(post(&s, body, out, sizeof out, &changed) == 400);
    snprintf(want, sizeof want, "{\"error\":\"%s\"}", reason);
    if (strcmp(out, want) != 0) {
        fprintf(stderr, "%s: got %s, want %s\n", body, out, want);
        assert(0);
    }
    assert(!changed);
    assert(fwe_webapp_handle(&s, "GET", "/api/settings", NULL, 0, out, sizeof out, &changed) == 200);
    assert(strcmp(out, DEFAULTS) == 0);
}

static void test_post_refuses_bad_bodies(void)
{
    expect_400("{\"volume_mb\":-1000,\"volume_mb\":1}", "bad volume_mb");
    expect_400("{\"volume_mb\":-6001}", "bad volume_mb");
    expect_400("{\"mid_mb\":1201}", "bad mid_mb");
    expect_400("{\"input\":\"bt\",\"xover_hz\":39}", "bad xover_hz");
    expect_400("{\"xover_hz\":201}", "bad xover_hz");
    expect_400("{\"sub1_level_mb\":1201}", "bad sub1_level_mb");
    expect_400("{\"sub1_delay_us\":20001}", "bad sub1_delay_us");
    expect_400("{\"sub2_delay_us\":-1}", "bad sub2_delay_us");
    expect_400("{\"xover_hz\":80.5}", "bad json");
    expect_400("{\"xover_hz\":\"80\"}", "bad xover_hz");
    expect_400("{\"volume_mb\":-9999999999}", "bad volume_mb");   /* too many digits to overflow */
    expect_400("{\"input\":\"aux\"}", "bad input");
    expect_400("{\"input\":3}", "bad input");
    expect_400("{\"gain\":0}", "unknown key");
    expect_400("{\"in\\put\":\"bt\"}", "bad json");
    expect_400("", "bad json");
    expect_400("[]", "bad json");
    expect_400("{\"volume_mb\":-100", "bad json");
    expect_400("{\"volume_mb\":-100,}", "bad json");
    expect_400("{\"volume_mb\":-100} x", "bad json");
    expect_400("{\"volume_mb\" -100}", "bad json");
}

static void test_other_requests(void)
{
    fwe_settings_t s;
    char out[512];
    bool changed;
    fwe_settings_default(&s);
    assert(fwe_webapp_handle(&s, "GET", "/api/other", NULL, 0, out, sizeof out, &changed) == 404);
    assert(strcmp(out, "{\"error\":\"not found\"}") == 0);
    assert(fwe_webapp_handle(&s, "DELETE", "/api/settings", NULL, 0, out, sizeof out, &changed) == 405);
    /* the body is bounded by its length, not a NUL */
    assert(fwe_webapp_handle(&s, "POST", "/api/settings", "{\"volume_mb\":-30}junk", 17, out, sizeof out,
                             &changed) == 200);
    assert(changed && s.volume_mb == -30);
    /* an answer that doesn't fit is a 500, never a truncated 200 */
    assert(fwe_webapp_handle(&s, "GET", "/api/settings", NULL, 0, out, 40, &changed) == 500);
    fwe_settings_default(&s);
    assert(fwe_settings_json(&s, out, strlen(DEFAULTS)) == -1);
    assert(fwe_settings_json(&s, out, strlen(DEFAULTS) + 1) == (int)strlen(DEFAULTS));
    s.input = FWE_INPUT_COUNT;   /* a bad value read back from NVS */
    assert(fwe_settings_json(&s, out, sizeof out) == -1);
}

static int st(const fwe_selftest_ops_t *ops, const char *body, char *out, size_t len)
{
    return fwe_webapp_selftest(ops, "POST", body, strlen(body), out, len);
}

static void test_selftest_route(void)
{
    fwe_st_tone_t tone = {0};
    fwe_selftest_ops_t ops = {.rails = fake_rails, .tone = fake_tone, .ctx = &tone};
    char out[128];
    /* the console's own line, as serial and TCP answer it */
    assert(st(&ops, "st rails", out, sizeof out) == 200);
    assert(strcmp(out, "OK {\"vbus_mv\":20000}\n") == 0);
    assert(st(&ops, "st tone VINL1 1000 -20\r\n", out, sizeof out) == 200);
    assert(strcmp(out, "OK {\"thd_pct\":0.01}\n") == 0);
    assert(strcmp(tone.tap, "VINL1") == 0 && tone.hz == 1000 && tone.dbfs == -20.0);
    /* a command the board doesn't support, or bad arguments, is still the console's ERR line */
    assert(st(&ops, "st pd", out, sizeof out) == 200 && strcmp(out, "ERR not supported\n") == 0);
    assert(st(&ops, "st tone VINL1 5 -20", out, sizeof out) == 200 && strncmp(out, "ERR bad hz", 10) == 0);
    /* a body that isn't an st command */
    assert(st(&ops, "", out, sizeof out) == 400 && strcmp(out, "{\"error\":\"not an st command\"}") == 0);
    assert(st(&ops, "reboot", out, sizeof out) == 400);
    assert(fwe_webapp_selftest(&ops, "POST", "st rails\0x", 10, out, sizeof out) == 400);
    char big[FWE_WEBAPP_ST_MAX + 2];
    memset(big, ' ', sizeof big - 1);
    memcpy(big, "st rails", 8);
    big[sizeof big - 1] = '\0';
    assert(st(&ops, big, out, sizeof out) == 400 && strcmp(out, "{\"error\":\"body too long\"}") == 0);
    big[sizeof big - 2] = '\0';  /* FWE_WEBAPP_ST_MAX exactly is in */
    assert(st(&ops, big, out, sizeof out) == 200);
    /* the body is bounded by its length, not a NUL */
    assert(fwe_webapp_selftest(&ops, "POST", "st railsjunk", 8, out, sizeof out) == 200);
    assert(strncmp(out, "OK ", 3) == 0);
    assert(fwe_webapp_selftest(&ops, "GET", NULL, 0, out, sizeof out) == 405);
    assert(fwe_webapp_selftest(&ops, "POST", "st rails", 8, out, 31) == 500);
}

/* A fake NVS namespace: up to 16 keys, and a write that fails after `writes_left` writes. */
typedef struct {
    char key[16][16];
    int32_t val[16];
    int n, writes, writes_left;
} fake_nvs_t;

static int nvs_get(void *ctx, const char *key, int32_t *val)
{
    fake_nvs_t *nvs = ctx;
    for (int i = 0; i < nvs->n; i++) {
        if (strcmp(nvs->key[i], key) == 0) {
            *val = nvs->val[i];
            return 0;
        }
    }
    return -1;
}

static int nvs_set(void *ctx, const char *key, int32_t val)
{
    fake_nvs_t *nvs = ctx;
    if (nvs->writes_left-- <= 0) {
        return -1;
    }
    nvs->writes++;
    int i = 0;
    while (i < nvs->n && strcmp(nvs->key[i], key) != 0) {
        i++;
    }
    assert(i < 16 && strlen(key) <= 15);   /* NVS keys are at most 15 characters */
    if (i == nvs->n) {
        strcpy(nvs->key[nvs->n++], key);
    }
    nvs->val[i] = val;
    return 0;
}

static void test_nvs_load_and_save(void)
{
    fake_nvs_t nvs = {.writes_left = 100};
    fwe_settings_t s, back, def;
    char out[512], again[512];
    bool changed;
    fwe_settings_default(&def);
    /* an empty namespace loads the defaults */
    assert(fwe_settings_load(&back, nvs_get, &nvs) == 0);
    assert(fwe_settings_json(&back, out, sizeof out) > 0 && strcmp(out, DEFAULTS) == 0);
    /* a full save writes every key, and loading it back gives the same settings */
    fwe_settings_default(&s);
    assert(post(&s, "{\"input\":\"airplay\",\"volume_mb\":-900,\"mid_mb\":-300,\"xover_hz\":110,"
                    "\"sub1_level_mb\":-600,\"sub2_delay_us\":4500}", out, sizeof out, &changed) == 200);
    assert(fwe_settings_save(&s, NULL, nvs_set, &nvs) == 0 && nvs.writes == 10 && nvs.n == 10);
    assert(fwe_settings_load(&back, nvs_get, &nvs) == 10);
    assert(fwe_settings_json(&back, again, sizeof again) > 0 && strcmp(out, again) == 0);
    /* saving against the old settings writes only what changed */
    fwe_settings_t before = s;
    nvs.writes = 0;
    assert(post(&s, "{\"treble_mb\":600,\"input\":\"airplay\"}", out, sizeof out, &changed) == 200);
    assert(fwe_settings_save(&s, &before, nvs_set, &nvs) == 0 && nvs.writes == 1);
    assert(fwe_settings_save(&s, &s, nvs_set, &nvs) == 0 && nvs.writes == 1);
    /* a stored value out of the API's range keeps its default, and the rest still load */
    nvs_set(&nvs, "input", FWE_INPUT_COUNT);
    nvs_set(&nvs, "xover_hz", 20);
    nvs_set(&nvs, "volume_mb", 1);
    nvs_set(&nvs, "sub1_delay_us", -1);
    assert(fwe_settings_load(&back, nvs_get, &nvs) == 6);
    assert(back.input == def.input && back.xover_hz == def.xover_hz && back.volume_mb == def.volume_mb);
    assert(back.sub_delay_us[0] == 0 && back.eq_mb[FWE_EQ_TREBLE] == 600 && back.sub_delay_us[1] == 4500);
    /* a failed write stops the save */
    nvs.writes_left = 3;
    nvs.writes = 0;
    assert(fwe_settings_save(&s, NULL, nvs_set, &nvs) == -1 && nvs.writes == 3);
}

int main(void)
{
    test_get_answers_the_defaults();
    test_post_changes_only_what_it_names();
    test_post_refuses_bad_bodies();
    test_other_requests();
    test_selftest_route();
    test_nvs_load_and_save();
    printf("fwe_webapp: ok\n");
    return 0;
}
