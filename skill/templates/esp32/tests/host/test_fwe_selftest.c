#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "fwe_selftest.h"

/* Fake handlers: each writes what the test set, so the test checks the console, not a board. */
typedef struct {
    const char *json; /* NULL: fail with err */
    const char *err;
    int lie;          /* add this to the length returned */
    fwe_st_tone_t tone;
    int calls;
} fake_t;

static int fake(void *ctx, char *out, size_t len, const char **err)
{
    fake_t *f = ctx;
    f->calls++;
    if (!f->json) {
        *err = f->err;
        return -1;
    }
    return snprintf(out, len, "%s", f->json) + f->lie;
}

static int fake_tone(void *ctx, const fwe_st_tone_t *tone, char *out, size_t len, const char **err)
{
    ((fake_t *)ctx)->tone = *tone;
    return fake(ctx, out, len, err);
}

static fake_t f;
static const fwe_selftest_ops_t OPS = {fake, fake, fake_tone, fake, &f};
static char out[128];

static const char *ask(const fwe_selftest_ops_t *ops, const char *line)
{
    int n = fwe_selftest_line(ops, line, out, sizeof out);
    assert(n == 0 || (n == (int)strlen(out) && out[n - 1] == '\n' && !memchr(out, '\n', (size_t)n - 1))); /* one line */
    return out;
}

static void test_each_command_answers_ok_with_the_handlers_json(void)
{
    f = (fake_t){.json = "{\"vbus_mv\":20000}"};
    assert(strcmp(ask(&OPS, "st pd\r\n"), "OK {\"vbus_mv\":20000}\n") == 0);
    assert(strcmp(ask(&OPS, "  st   rails "), "OK {\"vbus_mv\":20000}\n") == 0);
    assert(strcmp(ask(&OPS, "st net"), "OK {\"vbus_mv\":20000}\n") == 0 && f.calls == 3);
    assert(strcmp(ask(&OPS, "st tone dac_l 1000 -12.5"), "OK {\"vbus_mv\":20000}\n") == 0);
    assert(strcmp(f.tone.tap, "dac_l") == 0 && f.tone.hz == 1000 && f.tone.dbfs == -12.5);
    /* the range ends are in */
    assert(strncmp(ask(&OPS, "st tone sub_1 20 -60"), "OK ", 3) == 0 && f.tone.hz == 20);
    assert(strncmp(ask(&OPS, "st tone IN4 20000 0"), "OK ", 3) == 0 && f.tone.dbfs == 0.0);
}

static void test_other_lines_are_not_ours(void)
{
    f = (fake_t){.json = "{}"};
    out[0] = 'x';
    assert(fwe_selftest_line(&OPS, "", out, sizeof out) == 0 && out[0] == 'x');
    assert(ask(&OPS, " \r\n")[0] == 'x');
    assert(ask(&OPS, "nvs get fwe volume_mb")[0] == 'x');
    assert(ask(&OPS, "stat")[0] == 'x' && f.calls == 0);
}

static void expect_err(const char *line, const char *answer)
{
    f = (fake_t){.json = "{}"};
    assert(strcmp(ask(&OPS, line), answer) == 0);
    assert(f.calls == 0); /* a bad line never reaches the board */
}

static void test_bad_lines_answer_err(void)
{
    expect_err("st", "ERR usage: st rails|pd|tone|net\n");
    expect_err("st volts", "ERR usage: st rails|pd|tone|net\n");
    expect_err("st pd now", "ERR takes no arguments\n");
    expect_err("st tone dac_l 1000", "ERR usage: st tone <tap> <hz> <dBFS>\n");
    expect_err("st tone dac_l 1000 -6 extra", "ERR usage: st tone <tap> <hz> <dBFS>\n");
    expect_err("st tone a b c d e f g h", "ERR usage: st tone <tap> <hz> <dBFS>\n");
    expect_err("st tone dac-l 1000 -6", "ERR bad tap\n");
    expect_err("st tone abcdefghijklmnop 1000 -6", "ERR bad tap\n");
    expect_err("st tone dac_l 19 -6", "ERR bad hz, 20 to 20000\n");
    expect_err("st tone dac_l 20001 -6", "ERR bad hz, 20 to 20000\n");
    expect_err("st tone dac_l 1k -6", "ERR bad hz, 20 to 20000\n");
    expect_err("st tone dac_l 1000 0.5", "ERR bad dBFS, -60 to 0\n");
    expect_err("st tone dac_l 1000 -60.1", "ERR bad dBFS, -60 to 0\n");
    expect_err("st tone dac_l 1000 -inf", "ERR bad dBFS, -60 to 0\n");
    expect_err("st tone dac_l 1000 -", "ERR bad dBFS, -60 to 0\n");
}

static void test_handler_failures_answer_err(void)
{
    fwe_selftest_ops_t none = {0};
    assert(strcmp(ask(&none, "st net"), "ERR not supported\n") == 0);
    assert(strcmp(ask(&none, "st tone dac_l 1000 -6"), "ERR not supported\n") == 0);

    f = (fake_t){.err = "no PD\ncontract"};
    assert(strcmp(ask(&OPS, "st pd"), "ERR no PD contract\n") == 0); /* kept on one line */
    f = (fake_t){.err = NULL};
    assert(strcmp(ask(&OPS, "st pd"), "ERR failed\n") == 0);

    f = (fake_t){.json = "{\"a\":1}\n{\"b\":2}"};
    assert(strcmp(ask(&OPS, "st rails"), "ERR bad handler output\n") == 0);
    f = (fake_t){.json = "[1,2]"};
    assert(strcmp(ask(&OPS, "st rails"), "ERR bad handler output\n") == 0);
    f = (fake_t){.json = "{}", .lie = 3}; /* claims more than it wrote */
    assert(strcmp(ask(&OPS, "st rails"), "ERR bad handler output\n") == 0);

    char big[200];
    memset(big, 'a', sizeof big);
    big[0] = '{';
    big[sizeof big - 2] = '}';
    big[sizeof big - 1] = '\0';
    f = (fake_t){.json = big};
    assert(strcmp(ask(&OPS, "st rails"), "ERR answer too long\n") == 0);
    /* the longest that fits: "OK " + json + "\n" + NUL in out */
    big[sizeof out - 7] = '}';
    big[sizeof out - 6] = '\0';
    assert(strncmp(ask(&OPS, "st rails"), "OK {aaa", 7) == 0 && strlen(out) == sizeof out - 2);
}

static void test_pcm1863_mux_selects_each_tap(void)
{
    static const struct {
        const char *tap;
        uint8_t reg, val;
    } want[] = {{"VINL1", 0x06, 0x41}, {"VINL2", 0x06, 0x42}, {"VINL3", 0x06, 0x44}, {"VINL4", 0x06, 0x48},
                {"VINR1", 0x07, 0x41}, {"VINR2", 0x07, 0x42}, {"VINR3", 0x07, 0x44}, {"VINR4", 0x07, 0x48}};
    uint8_t reg, val;
    for (size_t i = 0; i < sizeof want / sizeof want[0]; i++) {
        reg = val = 0;
        assert(fwe_st_pcm1863_mux(want[i].tap, &reg, &val) == 0);
        assert(reg == want[i].reg && val == want[i].val);
    }
    /* anything else is an unknown tap, and leaves reg and val alone */
    static const char *bad[] = {"VINL0", "VINL5", "VINX1", "vinl1", "VINL1x", "VINL", "", "dac_l"};
    for (size_t i = 0; i < sizeof bad / sizeof bad[0]; i++) {
        reg = val = 0xEE;
        assert(fwe_st_pcm1863_mux(bad[i], &reg, &val) == -1 && reg == 0xEE && val == 0xEE);
    }
    assert(fwe_st_pcm1863_mux(NULL, &reg, &val) == -1);
}

static int32_t pcm[48000];

static void test_tone_reads_back_at_its_level(void)
{
    static const struct {
        unsigned hz;
        double dbfs;
    } tone[] = {{1000, -20.0}, {20, -6.0}, {20000, -60.0}, {997, 0.0}, {440, -45.5}};
    for (size_t i = 0; i < sizeof tone / sizeof tone[0]; i++) {
        fwe_st_tone_fill(pcm, 48000, 0, 48000, tone[i].hz, tone[i].dbfs);
        assert(fabs(fwe_st_tone_level(pcm, 48000, 48000, tone[i].hz) - tone[i].dbfs) < 0.05);
        /* 100 ms is enough at 1 kHz, and a part-cycle at the end doesn't matter */
        assert(fabs(fwe_st_tone_level(pcm, 4801, 48000, tone[i].hz) - tone[i].dbfs) < 0.1 || tone[i].hz < 100);
    }
    /* 0 dBFS peaks at full scale and no further */
    fwe_st_tone_fill(pcm, 48, 12, 48000, 1000, 0.0);
    assert(pcm[0] == INT32_MAX && pcm[24] == -INT32_MAX);
}

static void test_tone_fill_is_continuous_across_buffers(void)
{
    static int32_t part[1000];
    fwe_st_tone_fill(pcm, 48000, 0, 44100, 1234, -3.0);
    /* a day into the tone, buffers line up with one long fill */
    for (uint64_t start = 0; start < 48000; start += 1000) {
        fwe_st_tone_fill(part, 1000, start + 44100ull * 86400, 44100, 1234, -3.0);
        assert(memcmp(part, pcm + start, sizeof part) == 0);
    }
}

static void test_tone_level_rejects_other_content(void)
{
    /* the wrong tap: a 1 kHz tone, read at 2 kHz, is far down */
    fwe_st_tone_fill(pcm, 4800, 0, 48000, 1000, 0.0);
    assert(fwe_st_tone_level(pcm, 4800, 48000, 2000) < -80.0);
    /* DC and 50 Hz hum at -6 dBFS each barely move a -40 dBFS tone */
    static int32_t hum[4800];
    fwe_st_tone_fill(hum, 4800, 0, 48000, 50, -6.0);
    fwe_st_tone_fill(pcm, 4800, 0, 48000, 1000, -40.0);
    for (size_t i = 0; i < 4800; i++) pcm[i] += hum[i] / 2 + INT32_MAX / 4;
    assert(fabs(fwe_st_tone_level(pcm, 4800, 48000, 1000) - (-40.0)) < 0.1);
    /* silence, no samples or no rate read the floor, never -inf */
    memset(pcm, 0, sizeof pcm);
    assert(fwe_st_tone_level(pcm, 4800, 48000, 1000) == FWE_ST_TONE_FLOOR_DBFS);
    assert(fwe_st_tone_level(pcm, 0, 48000, 1000) == FWE_ST_TONE_FLOOR_DBFS);
    assert(fwe_st_tone_level(pcm, 4800, 0, 1000) == FWE_ST_TONE_FLOOR_DBFS);
}

int main(void)
{
    test_each_command_answers_ok_with_the_handlers_json();
    test_other_lines_are_not_ours();
    test_bad_lines_answer_err();
    test_handler_failures_answer_err();
    test_pcm1863_mux_selects_each_tap();
    test_tone_reads_back_at_its_level();
    test_tone_fill_is_continuous_across_buffers();
    test_tone_level_rejects_other_content();
    printf("fwe_selftest: ok\n");
    return 0;
}
