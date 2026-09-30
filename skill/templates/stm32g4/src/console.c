/* console.c - USART1 line console (reference/manifest.md, UART protocol).
 *
 * One command per '\n'-terminated line ('\r' ignored). Every command gets
 * exactly one reply line: "OK <json>" or "ERR <code> <text>". Events are
 * "EVT <json>" lines. Error codes are lowercase words:
 *   unknown  no such command          args     bad or missing arguments
 *   toolong  line over CONSOLE_LINE_MAX
 *   fault    refused: a fault is latched   state   refused in this state
 *   active   clear refused: the condition persists
 *   hwtrip   the hardware trip is not armed   adc   a conversion timed out
 *   selftest one or more self-test checks failed
 *   offsets  current offsets out of tolerance (nominal REF kept)
 * RX is interrupt-driven into a ring buffer; TX is blocking. */
#include <stddef.h>
#include "app.h"
#include "sense.h"

#define RX_SIZE 128u

static volatile uint8_t s_rx[RX_SIZE];
static volatile uint32_t s_rx_head, s_rx_tail;
static char s_line[CONSOLE_LINE_MAX + 1u];
static uint32_t s_len;
static int s_overlong;

void USART1_IRQHandler(void)
{
    uint32_t isr = USART1->ISR;
    if (isr & USART_ISR_ORE) USART1->ICR = USART_ICR_ORECF;
    if (isr & USART_ISR_RXNE_RXFNE) {
        uint8_t b = (uint8_t)USART1->RDR;
        uint32_t next = (s_rx_head + 1u) % RX_SIZE;
        if (next != s_rx_tail) {
            s_rx[s_rx_head] = b;
            s_rx_head = next;
        }
    }
}

static void putc_(char c)
{
    while (!(USART1->ISR & USART_ISR_TXE_TXFNF)) { }
    USART1->TDR = (uint8_t)c;
}

static void puts_(const char *s)
{
    while (*s) putc_(*s++);
}

/* --- a tiny JSON line builder (no printf: keeps float formatting small) --- */
static char s_out[320];
static size_t s_n;
static int s_first;

static void o_c(char c) { if (s_n + 1u < sizeof s_out) s_out[s_n++] = c; }
static void o_s(const char *s) { while (*s) o_c(*s++); }

static void o_u(uint32_t v)
{
    char t[11];
    int i = 0;
    do { t[i++] = (char)('0' + v % 10u); v /= 10u; } while (v);
    while (i) o_c(t[--i]);
}

static void o_f(float v) /* 3 decimals; NaN/inf -> null */
{
    if (v != v || v > 1e9f || v < -1e9f) { o_s("null"); return; }
    if (v < 0.0f) { o_c('-'); v = -v; }
    uint32_t m = (uint32_t)(v * 1000.0f + 0.5f);
    o_u(m / 1000u);
    o_c('.');
    uint32_t f = m % 1000u;
    o_c((char)('0' + f / 100u));
    o_c((char)('0' + f / 10u % 10u));
    o_c((char)('0' + f % 10u));
}

static void o_begin(const char *prefix) { s_n = 0; o_s(prefix); o_c('{'); s_first = 1; }
static void o_key(const char *k) { if (!s_first) o_c(','); s_first = 0; o_c('"'); o_s(k); o_s("\":"); }
static void o_kstr(const char *k, const char *v) { o_key(k); o_c('"'); o_s(v); o_c('"'); }
static void o_kbool(const char *k, int v) { o_key(k); o_s(v ? "true" : "false"); }
static void o_kf(const char *k, float v) { o_key(k); o_f(v); }
static void o_ku(const char *k, uint32_t v) { o_key(k); o_u(v); }
static void o_obj(const char *k) { o_key(k); o_c('{'); s_first = 1; }
static void o_close(void) { o_c('}'); s_first = 0; }

static void o_karr_f(const char *k, const float *v, int n)
{
    o_key(k);
    o_c('[');
    for (int i = 0; i < n; i++) { if (i) o_c(','); o_f(v[i]); }
    o_c(']');
}

static void o_kfaults(const char *k, uint32_t bits)
{
    o_key(k);
    o_c('[');
    int first = 1;
    for (uint32_t i = 0; i < FAULT_COUNT; i++) {
        if (bits & (1u << i)) {
            if (!first) o_c(',');
            first = 0;
            o_c('"'); o_s(fault_name(1u << i)); o_c('"');
        }
    }
    o_c(']');
}

static void o_send(void)
{
    s_out[s_n] = '\0';
    puts_(s_out);
    puts_("\r\n");
}

static void reply_ok(void) { o_close(); o_send(); }

static void reply_err(const char *code, const char *text)
{
    puts_("ERR ");
    puts_(code);
    puts_(" ");
    puts_(text);
    puts_("\r\n");
}

static void reply_err_faults(const char *code, uint32_t bits)
{
    s_n = 0;
    o_s("ERR ");
    o_s(code);
    o_c(' ');
    for (uint32_t i = 0, first = 1; i < FAULT_COUNT; i++) {
        if (bits & (1u << i)) {
            if (!first) o_c(',');
            first = 0;
            o_s(fault_name(1u << i));
        }
    }
    o_send();
}

/* --- init, banner, events --- */
void console_init(void)
{
    RCC->APB2ENR |= RCC_APB2ENR_USART1EN;
    (void)RCC->APB2ENR;
    gpio_af(PIN_UART_TX_PORT, PIN_UART_TX_PIN, PIN_UART_TX_AF);
    gpio_af(PIN_UART_RX_PORT, PIN_UART_RX_PIN, PIN_UART_RX_AF);
    PIN_UART_RX_PORT->PUPDR = (PIN_UART_RX_PORT->PUPDR & ~(3u << (PIN_UART_RX_PIN * 2u)))
                            | (1u << (PIN_UART_RX_PIN * 2u)); /* pull-up: idle high if unplugged */
    gpio_mode(PIN_UART_TX_PORT, PIN_UART_TX_PIN, GPIO_AF);
    gpio_mode(PIN_UART_RX_PORT, PIN_UART_RX_PIN, GPIO_AF);

    USART1->CR1 = 0u;
    USART1->BRR = (SystemCoreClock + UART_BAUD / 2u) / UART_BAUD; /* PCLK2 = SYSCLK, OVER16 */
    USART1->CR1 = USART_CR1_TE | USART_CR1_RE | USART_CR1_RXNEIE_RXFNEIE | USART_CR1_UE;
    NVIC_SetPriority(USART1_IRQn, 2u);
    NVIC_EnableIRQ(USART1_IRQn);
}

void console_boot(const char *reset_cause)
{
    puts_("fwe " BOARD_ID " " FW_VERSION " " FW_STAGE "\r\n");
    o_begin("EVT ");
    o_obj("boot");
    o_kstr("reset_cause", reset_cause);
    o_close();
    reply_ok();
}

void console_evt_fault(uint32_t fresh)
{
    o_begin("EVT ");
    o_obj("fault");
    o_kfaults("new", fresh);
    o_kfaults("latched", g_app.faults.latched);
    o_kf("vbus_v", g_app.vbus_v);
    o_karr_f("i_a", g_app.i_a, 3);
    o_close();
    reply_ok();
}

void console_evt_button(int level)
{
    o_begin("EVT ");
    o_obj("button");
    o_ku("level", (uint32_t)level);
    o_close();
    reply_ok();
}

/* --- commands --- */
static int streq(const char *a, const char *b)
{
    while (*a && *a == *b) { a++; b++; }
    return *a == *b;
}

/* "0", "1", "0.25", ".5": a plain decimal in 0..1, nothing else */
static int parse_unit(const char *s, float *out)
{
    float v = 0.0f, scale = 1.0f;
    int digits = 0, dot = 0;
    for (; *s; s++) {
        if (*s == '.' && !dot) { dot = 1; continue; }
        if (*s < '0' || *s > '9') return -1;
        digits++;
        if (dot) { scale *= 0.1f; v += (float)(*s - '0') * scale; }
        else v = v * 10.0f + (float)(*s - '0');
        if (digits > 9) return -1;
    }
    if (!digits || v > 1.0f) return -1;
    *out = v;
    return 0;
}

static void cmd_version(void)
{
    o_begin("OK ");
    o_kstr("board", BOARD_ID);
    o_kstr("mcu", BOARD_MCU);
    o_kstr("version", FW_VERSION);
    o_kstr("stage", FW_STAGE);
    reply_ok();
}

static void cmd_status(void)
{
    o_begin("OK ");
    o_kbool("armed", g_app.armed);
    o_kfaults("faults", g_app.faults.latched);
    o_kfaults("active", g_app.active);
    o_kf("vbus_v", g_app.vbus_v);
    o_karr_f("i_a", g_app.i_a, 3);
    o_karr_f("duty", g_app.duty, 3);
    o_kbool("hw_trip", g_app.hw_trip_ok);
    o_ku("uptime_ms", millis());
    reply_ok();
}

static void cmd_adc(void)
{
    static const char *const names[3] = { "isense_a", "isense_b", "isense_c" };
    adc_sample();
    o_begin("OK ");
    o_obj("raw");
    o_ku("vbus", g_app.raw_vbus);
    for (int k = 0; k < 3; k++) o_ku(names[k], g_app.raw_i[k]);
    o_close();
    o_obj("v");
    o_kf("vbus", sense_counts_to_v(g_app.raw_vbus, RAIL_VDDA_V));
    for (int k = 0; k < 3; k++) o_kf(names[k], sense_counts_to_v(g_app.raw_i[k], RAIL_VDDA_V));
    o_close();
    o_kf("vbus_v", g_app.vbus_v);
    o_karr_f("i_a", g_app.i_a, 3);
    o_karr_f("i_ref_v", g_app.i_ref_v, 3);
    o_kbool("ok", g_app.adc_ok);
    reply_ok();
}

static void cmd_offsets(void)
{
    if (g_app.armed) { reply_err("state", "armed: disarm first, offsets need the bridge off"); return; }
    int r = adc_calibrate_offsets();
    if (r == -1) { reply_err("adc", "conversion timeout"); return; }
    o_begin(r ? "ERR offsets " : "OK ");
    o_karr_f("i_ref_v", g_app.i_ref_v, 3);
    o_kbool("ok", g_app.offsets_ok);
    reply_ok();
}

static void cmd_selftest(void)
{
    int clk = clock_is_pll_170();
    adc_sample();
    int adc = g_app.adc_ok;
    int off = g_app.offsets_ok;
    int trip = HW_TRIP_ENABLE ? (g_app.hw_trip_ok && !pwm_hw_trip_active()) : 1;
    int pass = clk && adc && off && trip;
    o_begin(pass ? "OK " : "ERR selftest ");
    o_kbool("pass", pass);
    o_obj("checks");
    o_kbool("clock_170mhz", clk);
    o_kbool("adc", adc);
    o_kbool("offsets", off);
    o_kbool("hw_trip", trip);
    o_close();
    reply_ok();
}

static void cmd_led(int argc, char **argv)
{
    int which, mode;
    if (argc != 3) { reply_err("args", "led <status|fault> <on|off|auto>"); return; }
    if (streq(argv[1], "status")) which = 0;
    else if (streq(argv[1], "fault")) which = 1;
    else { reply_err("args", "led <status|fault> <on|off|auto>"); return; }
    if (streq(argv[2], "on")) mode = LED_ON;
    else if (streq(argv[2], "off")) mode = LED_OFF;
    else if (streq(argv[2], "auto")) mode = LED_AUTO;
    else { reply_err("args", "led <status|fault> <on|off|auto>"); return; }
    board_led_override(which, mode);
    o_begin("OK ");
    o_kstr("led", which ? "fault" : "status");
    o_kstr("mode", argv[2]);
    reply_ok();
}

static void cmd_arm(void)
{
    if (fault_is_latched(&g_app.faults)) { reply_err_faults("fault", g_app.faults.latched); return; }
    if (HW_TRIP_ENABLE && !g_app.hw_trip_ok) { reply_err("hwtrip", "hardware trip not armed"); return; }
    if (pwm_arm()) { reply_err("state", "break active, MOE held low"); return; }
    o_begin("OK ");
    o_kbool("armed", 1);
    o_karr_f("duty", g_app.duty, 3);
    reply_ok();
}

static void cmd_disarm(void)
{
    pwm_disarm();
    o_begin("OK ");
    o_kbool("armed", 0);
    reply_ok();
}

static void cmd_duty(int argc, char **argv)
{
    float d[3];
    if (argc != 4) { reply_err("args", "duty <a> <b> <c>, each 0..1"); return; }
    for (int k = 0; k < 3; k++)
        if (parse_unit(argv[k + 1], &d[k])) { reply_err("args", "duty <a> <b> <c>, each 0..1"); return; }
    if (fault_is_latched(&g_app.faults)) { reply_err_faults("fault", g_app.faults.latched); return; }
    if (!g_app.armed) { reply_err("state", "not armed"); return; }
    pwm_set_duty(d);
    o_begin("OK ");
    o_karr_f("duty", g_app.duty, 3);
    o_kf("max_duty", MAX_DUTY);
    reply_ok();
}

static void cmd_clear(void)
{
    uint32_t blocking = fault_clear(&g_app.faults, safety_active_now());
    if (blocking) { reply_err_faults("active", blocking); return; }
    pwm_break_flag_clear();
    o_begin("OK ");
    o_kfaults("faults", g_app.faults.latched);
    reply_ok();
}

static void cmd_reset(void)
{
    pwm_disarm();
    o_begin("OK ");
    o_kbool("reset", 1);
    reply_ok();
    while (!(USART1->ISR & USART_ISR_TC)) { }
    NVIC_SystemReset();
}

static void dispatch(char *line)
{
    char *argv[6];
    int argc = 0;
    for (char *p = line; *p && argc < 6;) {
        while (*p == ' ') *p++ = '\0';
        if (!*p) break;
        argv[argc++] = p;
        while (*p && *p != ' ') p++;
    }
    if (!argc) return; /* blank line: no reply */
    const char *c = argv[0];
    if (streq(c, "version")) cmd_version();
    else if (streq(c, "status")) cmd_status();
    else if (streq(c, "selftest")) cmd_selftest();
    else if (streq(c, "adc")) cmd_adc();
    else if (streq(c, "offsets")) cmd_offsets();
    else if (streq(c, "led")) cmd_led(argc, argv);
    else if (streq(c, "arm")) cmd_arm();
    else if (streq(c, "disarm")) cmd_disarm();
    else if (streq(c, "duty")) cmd_duty(argc, argv);
    else if (streq(c, "clear")) cmd_clear();
    else if (streq(c, "reset")) cmd_reset();
    else reply_err("unknown", "commands: version status selftest adc offsets led arm disarm duty clear reset");
}

void console_poll(void)
{
    while (s_rx_tail != s_rx_head) {
        char ch = (char)s_rx[s_rx_tail];
        s_rx_tail = (s_rx_tail + 1u) % RX_SIZE;
        if (ch == '\r') continue;
        if (ch == '\n') {
            if (s_overlong) reply_err("toolong", "line over CONSOLE_LINE_MAX");
            else { s_line[s_len] = '\0'; dispatch(s_line); }
            s_len = 0;
            s_overlong = 0;
            iwdg_kick();
        } else if (s_len < CONSOLE_LINE_MAX) {
            s_line[s_len++] = ch;
        } else {
            s_overlong = 1;
        }
    }
}
