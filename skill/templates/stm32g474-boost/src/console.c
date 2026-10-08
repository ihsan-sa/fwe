/* console.c - USART2 line console (reference/manifest.md, UART protocol).
 *
 * One command per '\n'-terminated line ('\r' ignored). Every command gets
 * exactly one reply line: "OK <json>" or "ERR <code> <text>". Events are
 * "EVT <json>" lines. Error codes are lowercase words:
 *   unknown  no such command          args     bad or missing arguments
 *   toolong  line over CONSOLE_LINE_MAX
 *   trip     refused: a trip is latched    state   refused in this mode
 *   active   refused: the condition (or a comparator output) persists
 *   hw       the hardware trips or the control sample are not running
 *   output   the HRTIM refused to enable the outputs (a fault input is active)
 *   selftest one or more self-test checks failed
 * vbus_v in status is the output (the high-voltage bus), so bench tools
 * written for the motor boards read the same key.
 * RX is interrupt-driven into a ring buffer; TX is blocking. */
#include <stddef.h>
#include "app.h"
#include "scale.h"

#define RX_SIZE 128u

static volatile uint8_t s_rx[RX_SIZE];
static volatile uint32_t s_rx_head, s_rx_tail;
static char s_line[CONSOLE_LINE_MAX + 1u];
static uint32_t s_len;
static int s_overlong;

void USART2_IRQHandler(void)
{
    uint32_t isr = USART2->ISR;
    if (isr & USART_ISR_ORE) USART2->ICR = USART_ICR_ORECF;
    if (isr & USART_ISR_RXNE_RXFNE) {
        uint8_t b = (uint8_t)USART2->RDR;
        uint32_t next = (s_rx_head + 1u) % RX_SIZE;
        if (next != s_rx_tail) {
            s_rx[s_rx_head] = b;
            s_rx_head = next;
        }
    }
}

static void putc_(char c)
{
    while (!(USART2->ISR & USART_ISR_TXE_TXFNF)) { }
    USART2->TDR = (uint8_t)c;
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

static void o_ktrips(const char *k, uint32_t bits)
{
    o_key(k);
    o_c('[');
    int first = 1;
    for (uint32_t i = 0; i < TRIP_COUNT; i++) {
        if (bits & (1u << i)) {
            if (!first) o_c(',');
            first = 0;
            o_c('"'); o_s(trip_name(1u << i)); o_c('"');
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

static void reply_err_trips(const char *code, uint32_t bits)
{
    s_n = 0;
    o_s("ERR ");
    o_s(code);
    o_c(' ');
    for (uint32_t i = 0, first = 1; i < TRIP_COUNT; i++) {
        if (bits & (1u << i)) {
            if (!first) o_c(',');
            first = 0;
            o_s(trip_name(1u << i));
        }
    }
    o_send();
}

/* --- init, banner, events --- */
void console_init(void)
{
    RCC->APB1ENR1 |= RCC_APB1ENR1_USART2EN;
    (void)RCC->APB1ENR1;
    gpio_af(PIN_UART_TX_PORT, PIN_UART_TX_PIN, PIN_UART_TX_AF);
    gpio_af(PIN_UART_RX_PORT, PIN_UART_RX_PIN, PIN_UART_RX_AF);
    PIN_UART_RX_PORT->PUPDR = (PIN_UART_RX_PORT->PUPDR & ~(3u << (PIN_UART_RX_PIN * 2u)))
                            | (1u << (PIN_UART_RX_PIN * 2u)); /* pull-up: idle high if unplugged */
    gpio_mode(PIN_UART_TX_PORT, PIN_UART_TX_PIN, GPIO_AF);
    gpio_mode(PIN_UART_RX_PORT, PIN_UART_RX_PIN, GPIO_AF);

    USART2->CR1 = 0u;
    USART2->BRR = (SystemCoreClock + UART_BAUD / 2u) / UART_BAUD; /* PCLK1 = SYSCLK, OVER16 */
    USART2->CR1 = USART_CR1_TE | USART_CR1_RE | USART_CR1_RXNEIE_RXFNEIE | USART_CR1_UE;
    NVIC_SetPriority(USART2_IRQn, 2u);
    NVIC_EnableIRQ(USART2_IRQn);
}

void console_boot(const char *reset_cause)
{
    puts_("fwe " BOARD_ID " " FW_VERSION " " FW_STAGE "\r\n");
    o_begin("EVT ");
    o_obj("boot");
    o_kstr("reset_cause", reset_cause);
    o_kbool("hw_ok", g_app.hw_ok);
    o_close();
    reply_ok();
}

void console_evt_trip(uint32_t fresh)
{
    o_begin("EVT ");
    o_obj("trip");
    o_ktrips("new", fresh);
    o_ktrips("latched", g_app.trips.latched);
    o_kf("vout_v", g_app.vout_v);
    o_kf("vin_v", g_app.vin_v);
    o_kf("il_a", g_app.il_a);
    o_kf("temp_c", g_app.temp_c);
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

/* the reply for a refused safety_arm / safety_open */
static void reply_refused(int r)
{
    if (r == -1) reply_err_trips("trip", g_app.trips.latched);
    else if (r == -2) reply_err_trips("active", safety_active_now() | hrtim_fault_flags());
    else if (r == -3) reply_err("hw", "hardware trips or control sample not running");
    else if (r == -5) reply_err("state", "regulating: disarm first");
    else reply_err("args", "bad value");
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
    o_kstr("state", safety_mode_name());
    o_kbool("outputs_on", hrtim_outputs_are_on());
    o_ktrips("trips", g_app.trips.latched);
    o_ktrips("active", safety_active_now());
    o_kf("vbus_v", g_app.vout_v);
    o_kf("vout_v", g_app.vout_v);
    o_kf("vin_v", g_app.vin_v);
    o_kf("il_a", g_app.il_a);
    o_kf("temp_c", g_app.temp_c);
    o_kf("duty", g_app.duty);
    o_kf("vref_v", g_app.vref_v);
    o_kbool("derated", g_app.derated);
    o_obj("hw");
    uint32_t comp = comp_active(), flt = hrtim_fault_flags();
    o_kbool("ovp_comp", (comp & TRIP_OVP_HW) != 0u);
    o_kbool("ocp_comp", (comp & TRIP_OCP_HW) != 0u);
    o_kbool("ovp_flt", (flt & TRIP_OVP_HW) != 0u);
    o_kbool("ocp_flt", (flt & TRIP_OCP_HW) != 0u);
    o_kbool("ok", g_app.hw_ok);
    o_close();
    o_kf("fan", fan_duty());
    o_ku("samples", g_app.samples);
    o_ku("uptime_ms", millis());
    reply_ok();
}

static void cmd_adc(void)
{
    static const char *const names[4] = { "isns", "vout", "vin", "ntc" };
    uint16_t raw[4];
    __disable_irq();
    for (int k = 0; k < 4; k++) raw[k] = g_app.raw[k];
    __enable_irq();
    o_begin("OK ");
    o_obj("raw");
    for (int k = 0; k < 4; k++) o_ku(names[k], raw[k]);
    o_close();
    o_obj("v");
    for (int k = 0; k < 4; k++) o_kf(names[k], scale_counts_v(raw[k], RAIL_VDDA_V));
    o_close();
    o_kf("ovp_threshold_v", comp_threshold_v(TRIP_OVP_HW));
    o_kf("ocp_threshold_v", comp_threshold_v(TRIP_OCP_HW));
    o_kbool("ok", g_app.adc_ok);
    reply_ok();
}

static void cmd_selftest(void)
{
    int clk = clock_is_pll_170();
    int dll = hrtim_dll_ready();
    int hw = g_app.hw_ok;
    int adc = g_app.adc_ok;
    int quiet = !comp_active() && !hrtim_fault_flags();
    int pass = clk && dll && hw && adc && quiet;
    o_begin(pass ? "OK " : "ERR selftest ");
    o_kbool("pass", pass);
    o_obj("checks");
    o_kbool("clock_170mhz", clk);
    o_kbool("hrtim_dll", dll);
    o_kbool("hw_trips", hw);
    o_kbool("adc", adc);
    o_kbool("comparators_low", quiet);
    o_close();
    reply_ok();
}

static void cmd_arm(void)
{
    int r = safety_arm();
    if (r) { reply_refused(r); return; }
    o_begin("OK ");
    o_kstr("state", safety_mode_name());
    o_kf("target_v", VOUT_TARGET_V);
    o_kf("vref_v", g_app.vref_v);
    reply_ok();
}

static void cmd_disarm(void)
{
    safety_disarm();
    o_begin("OK ");
    o_kstr("state", safety_mode_name());
    o_kbool("outputs_on", hrtim_outputs_are_on());
    reply_ok();
}

static void cmd_duty(int argc, char **argv)
{
    float d;
    if (argc != 2 || parse_unit(argv[1], &d)) { reply_err("args", "duty <d>, 0..1 (capped at d_max)"); return; }
    int r = safety_open(d);
    if (r) { reply_refused(r); return; }
    o_begin("OK ");
    o_kstr("state", safety_mode_name());
    o_kf("duty", g_app.duty);
    o_kf("d_max", D_MAX);
    reply_ok();
}

static void cmd_clear(void)
{
    __disable_irq();
    uint32_t comp = comp_active();
    uint32_t blocking = trip_clear(&g_app.trips, safety_active_now()) | comp;
    if (!comp) hrtim_fault_flags_clear(); /* comparators are low: the FLTn flags may go */
    __enable_irq();
    if (blocking) { reply_err_trips("active", blocking); return; }
    o_begin("OK ");
    o_ktrips("trips", g_app.trips.latched);
    reply_ok();
}

static void cmd_fan(int argc, char **argv)
{
    int pct = 0;
    if (argc == 2 && streq(argv[1], "auto")) pct = -1;
    else {
        const char *s = argc == 2 ? argv[1] : "";
        if (!*s) { reply_err("args", "fan <0..100|auto>"); return; }
        for (; *s; s++) {
            if (*s < '0' || *s > '9' || pct > 100) { reply_err("args", "fan <0..100|auto>"); return; }
            pct = pct * 10 + (*s - '0');
        }
        if (pct > 100) { reply_err("args", "fan <0..100|auto>"); return; }
    }
    fan_override(pct);
    o_begin("OK ");
    o_kbool("auto", fan_is_auto());
    o_kf("fan", fan_duty());
    reply_ok();
}

static void cmd_reset(void)
{
    safety_disarm();
    o_begin("OK ");
    o_kbool("reset", 1);
    reply_ok();
    while (!(USART2->ISR & USART_ISR_TC)) { }
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
    else if (streq(c, "arm")) cmd_arm();
    else if (streq(c, "disarm")) cmd_disarm();
    else if (streq(c, "duty")) cmd_duty(argc, argv); /* fwe-cmd args="<d 0..1>" safe=no */
    else if (streq(c, "clear")) cmd_clear();
    else if (streq(c, "fan")) cmd_fan(argc, argv); /* fwe-cmd args="<0..100|auto>" safe=yes */
    else if (streq(c, "reset")) cmd_reset();
    else reply_err("unknown", "commands: version status selftest adc arm disarm duty clear fan reset");
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
