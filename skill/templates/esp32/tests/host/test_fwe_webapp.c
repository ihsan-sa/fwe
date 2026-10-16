#include <assert.h>
#include <stdio.h>
#include <string.h>

#include "fwe_webapp.h"

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

int main(void)
{
    test_get_answers_the_defaults();
    test_post_changes_only_what_it_names();
    test_post_refuses_bad_bodies();
    test_other_requests();
    printf("fwe_webapp: ok\n");
    return 0;
}
