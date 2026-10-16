#include "fwe_selftest.h"

#include <stdlib.h>
#include <string.h>

#define MAX_TOKENS 6

typedef struct {
    const char *p;
    size_t n;
} tok_t;

static int is_space(char c) { return c == ' ' || c == '\t' || c == '\r' || c == '\n'; }

static int split(const char *line, tok_t *t)
{
    int k = 0;
    while (*line) {
        while (is_space(*line)) line++;
        if (!*line) break;
        if (k == MAX_TOKENS) return k + 1; /* more than any command takes */
        t[k].p = line;
        while (*line && !is_space(*line)) line++;
        t[k].n = (size_t)(line - t[k].p);
        k++;
    }
    return k;
}

static int tok_is(const tok_t *t, const char *s) { return t->n == strlen(s) && memcmp(t->p, s, t->n) == 0; }

/* ERR <reason>\n, the reason cut to fit and kept on one line. */
static int answer_err(const char *reason, char *out, size_t out_len)
{
    size_t n = 4;
    memcpy(out, "ERR ", 4);
    if (!reason || !*reason) reason = "failed";
    for (; *reason && n + 2 < out_len; reason++) out[n++] = is_space(*reason) ? ' ' : *reason;
    out[n++] = '\n';
    out[n] = '\0';
    return (int)n;
}

static int parse_tap(const tok_t *t, char *tap)
{
    if (t->n == 0 || t->n > FWE_ST_TAP_MAX) return -1;
    for (size_t i = 0; i < t->n; i++) {
        char c = t->p[i];
        if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_')) return -1;
    }
    memcpy(tap, t->p, t->n);
    tap[t->n] = '\0';
    return 0;
}

static int parse_hz(const tok_t *t, unsigned *hz)
{
    unsigned v = 0;
    if (t->n == 0 || t->n > 5) return -1;
    for (size_t i = 0; i < t->n; i++) {
        if (t->p[i] < '0' || t->p[i] > '9') return -1;
        v = v * 10 + (unsigned)(t->p[i] - '0');
    }
    if (v < FWE_ST_TONE_MIN_HZ || v > FWE_ST_TONE_MAX_HZ) return -1;
    *hz = v;
    return 0;
}

static int parse_dbfs(const tok_t *t, double *dbfs)
{
    char buf[16];
    char *end;
    if (t->n == 0 || t->n >= sizeof buf) return -1;
    for (size_t i = 0; i < t->n; i++) {
        char c = t->p[i];
        if (!((c >= '0' && c <= '9') || c == '-' || c == '+' || c == '.')) return -1; /* no inf, nan or hex */
    }
    memcpy(buf, t->p, t->n);
    buf[t->n] = '\0';
    double v = strtod(buf, &end);
    if (*end || !(v >= FWE_ST_TONE_MIN_DBFS && v <= 0.0)) return -1;
    *dbfs = v;
    return 0;
}

/* OK {json}\n, when the handler wrote one object on one line that fits. */
static int answer_ok(int n, const char *err, char *out, size_t out_len)
{
    char *json = out + 3;
    if (n < 0) return answer_err(err, out, out_len);
    if ((size_t)n + 5 >= out_len) return /* n at the handler's buffer size: snprintf cut it */ answer_err("answer too long", out, out_len);
    if (n < 2 || json[0] != '{' || json[n - 1] != '}' || memchr(json, '\0', (size_t)n) ||
        memchr(json, '\n', (size_t)n) || memchr(json, '\r', (size_t)n))
        return answer_err("bad handler output", out, out_len);
    memcpy(out, "OK ", 3);
    out[3 + n] = '\n';
    out[4 + n] = '\0';
    return n + 4;
}

int fwe_selftest_line(const fwe_selftest_ops_t *ops, const char *line, char *out, size_t out_len)
{
    tok_t t[MAX_TOKENS];
    const char *err = NULL;
    int k = split(line, t);
    fwe_st_fn fn = NULL;

    if (k == 0 || !tok_is(&t[0], "st")) return 0;
    out[0] = '\0';
    if (k == 1) return answer_err("usage: st rails|pd|tone|net", out, out_len);

    if (tok_is(&t[1], "tone")) {
        fwe_st_tone_t tone;
        if (k != 5) return answer_err("usage: st tone <tap> <hz> <dBFS>", out, out_len);
        if (parse_tap(&t[2], tone.tap)) return answer_err("bad tap", out, out_len);
        if (parse_hz(&t[3], &tone.hz)) return answer_err("bad hz, 20 to 20000", out, out_len);
        if (parse_dbfs(&t[4], &tone.dbfs)) return answer_err("bad dBFS, -60 to 0", out, out_len);
        if (!ops->tone) return answer_err("not supported", out, out_len);
        memset(out + 3, 0, out_len - 3);
        int n = ops->tone(ops->ctx, &tone, out + 3, out_len - 5, &err);
        return answer_ok(n, err, out, out_len);
    }
    if (tok_is(&t[1], "rails")) fn = ops->rails;
    else if (tok_is(&t[1], "pd")) fn = ops->pd;
    else if (tok_is(&t[1], "net")) fn = ops->net;
    else return answer_err("usage: st rails|pd|tone|net", out, out_len);
    if (k != 2) return answer_err("takes no arguments", out, out_len);
    if (!fn) return answer_err("not supported", out, out_len);
    memset(out + 3, 0, out_len - 3);
    int n = fn(ops->ctx, out + 3, out_len - 5, &err);
    return answer_ok(n, err, out, out_len);
}

int fwe_st_pcm1863_mux(const char *tap, uint8_t *reg, uint8_t *val)
{
    if (!tap || strncmp(tap, "VIN", 3) != 0 || (tap[3] != 'L' && tap[3] != 'R') || tap[4] < '1' ||
        tap[4] > '4' || tap[5] != '\0')
        return -1;
    *reg = tap[3] == 'L' ? FWE_PCM1863_REG_ADC1_SEL_L : FWE_PCM1863_REG_ADC1_SEL_R;
    *val = (uint8_t)(FWE_PCM1863_SEL_BASE | (1u << (tap[4] - '1')));
    return 0;
}
