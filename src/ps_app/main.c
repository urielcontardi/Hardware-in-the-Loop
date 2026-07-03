#include "gpio.h"
#include "vf_ctrl.h"
#include "telemetry.h"
#include "dma_telem.h"
#include "pwm_events.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <time.h>
#include <unistd.h>
#include <fcntl.h>
#include <pthread.h>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <sys/ioctl.h>
#include <net/if.h>
#include <ifaddrs.h>
#include <math.h>
#include <sys/file.h>   /* flock — single-instance guard */

#ifndef PS_VERSION
#define PS_VERSION "dev"
#endif
typedef struct {
    float rs;
    float rr;
    float ls;
    float lr;
    float lm;
    float j;
    float npp;
} motor_params_t;

static motor_params_t motor_params = {
    .rs = 0.435f,
    .rr = 0.2826f,
    .ls = 3.1364e-3f,
    .lr = 6.3264e-3f,
    .lm = 109.9442e-3f,
    .j = 0.192f,
    .npp = 2.0f,
};

/* UDP command port */
#define UDP_PORT        5005
#define DISCOVERY_PORT  5004
#define DISCOVERY_MAGIC "HIL_DISCOVER_V1"
#define BOARD_NAME      "ebaz4205"

/* Monitor scale: 32 MSBs of Q14.28 → divide by 2^18 to get float */
#define MON_SCALE  (1.0f / (float)(1 << 18))

/* ── Daemon state ────────────────────────────────────────────────────────── */
typedef enum {
    HIL_IDLE    = 0,   /* power-on default — nothing configured */
    HIL_RUNNING = 1,   /* motor enabled, solver driving */
    HIL_PAUSED  = 2,   /* motor disabled, params preserved */
    HIL_STOPPED = 3,   /* motor disabled, params reset to safe defaults */
} hil_state_t;

static const char *state_name(hil_state_t s)
{
    switch (s) {
        case HIL_IDLE:    return "idle";
        case HIL_RUNNING: return "running";
        case HIL_PAUSED:  return "paused";
        case HIL_STOPPED: return "stopped";
        default:          return "unknown";
    }
}

static volatile int          running    = 1;          /* daemon lifetime    */
static volatile hil_state_t  hil_state  = HIL_IDLE;   /* control-FSM state  */
static char                  telem_dst_ip[INET_ADDRSTRLEN] = {0};

static int program_motor_coeffs(const motor_params_t *m);

/* ── V/F reference clock on a dedicated thread ──────────────────────────── */
static pthread_t vf_clock_tid;
static volatile int vf_clock_active = 0;

static void *vf_clock_thread(void *arg)
{
    (void)arg;
    struct timespec next;
    clock_gettime(CLOCK_MONOTONIC, &next);
    while (running && vf_clock_active) {
        next.tv_nsec += 1000000000L / VF_TICK_HZ;
        if (next.tv_nsec >= 1000000000L) {
            next.tv_sec++;
            next.tv_nsec -= 1000000000L;
        }
        clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &next, NULL);
        if (vf_clock_active) vf_tick();
    }
    return NULL;
}

static void set_udp_reuse(int sock)
{
    int yes = 1;
    /* SO_REUSEADDR only — allows a clean rebind after a restart. We deliberately
     * do NOT set SO_REUSEPORT: that would let a second hil_controller instance
     * bind the same port and silently coexist, and two instances each driving
     * the FPGA at 1 kHz produce conflicting pwm_ctrl writes (enable toggles →
     * epoch spins, state oscillates running/paused). Without SO_REUSEPORT, a
     * duplicate instance fails bind() with EADDRINUSE and exits — exactly what
     * we want, since inittab already keeps one instance alive. */
    setsockopt(sock, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));
}

static int setup_vf_timer(void)
{
    /* Release any clear/reset state left by boot or test_fpga. */
    vf_tick();
    vf_clock_active = 1;
    if (pthread_create(&vf_clock_tid, NULL, vf_clock_thread, NULL) != 0) {
        vf_clock_active = 0;
        perror("pthread_create vf_clock");
        return -1;
    }
    return 0;
}

static void cancel_timer(void)
{
    if (!vf_clock_active) return;
    vf_clock_active = 0;
    pthread_join(vf_clock_tid, NULL);
}

/* ── Telemetry thread — reads solver monitors, pushes UDP bursts ────────── */

#define TELEM_DEFAULT_HZ   10000u
#define TELEM_MIN_HZ        1000u
#define TELEM_MAX_GPIO_HZ  50000u

static volatile unsigned telem_sample_hz = TELEM_DEFAULT_HZ;
static int use_dma = 0;    /* set to 1 if DMA init succeeds */

static pthread_t telem_tid;
static volatile int telem_active = 0;

static unsigned clamp_telem_hz(unsigned hz)
{
    if (hz == 0) return TELEM_DEFAULT_HZ;
    if (hz < TELEM_MIN_HZ) return TELEM_MIN_HZ;
    if (hz > TELEM_MAX_GPIO_HZ) return TELEM_MAX_GPIO_HZ;
    return hz;
}

static void set_telem_hz(unsigned hz)
{
    telem_sample_hz = clamp_telem_hz(hz);
}

static long telem_period_ns(void)
{
    unsigned hz = telem_sample_hz;
    if (hz == 0) hz = TELEM_DEFAULT_HZ;
    return (long)(1000000000ULL / (uint64_t)hz);
}

static const char *telem_source_name(void)
{
    return use_dma ? "dma" : "gpio";
}

/*
 * DMA telemetry thread — transfers DMA_BURST_FRAMES samples per DMA call,
 * then pushes each sample through the UDP telemetry path. Falls back to
 * the legacy GPIO-polling path if DMA init fails.
 *
 * Rate:
 *   DMA burst = DMA_BURST_FRAMES at ~100 kHz with decim=77.
 *   Each DMA sample is forwarded through the existing UDP telemetry path.
 */
static void *telem_thread_fn(void *arg)
{
    (void)arg;
    sigset_t set;
    sigemptyset(&set);
    sigaddset(&set, SIGRTMIN);
    pthread_sigmask(SIG_BLOCK, &set, NULL);

    if (use_dma) {
        /* ── DMA double-buffer path ────────────────────────────────── */
        dma_sample_t dma_buf[DMA_BURST_FRAMES];
        int dma_errors = 0;
        while (running && telem_active) {
            /* dma_telem_next: waits for active buffer, re-arms the other,
             * then decodes — DMA is always running with minimal gap. */
            int n = dma_telem_next(dma_buf, 500 /* ms timeout */);
            if (n == 0) {
                /* Transient DMAIntErr at run/reset boundaries: DMA was reset and
                 * re-armed, but there is no completed burst to forward. Do not
                 * count this toward the GPIO fallback threshold. */
                dma_errors = 0;
                continue;
            }
            if (n < 0) {
                if (++dma_errors >= 3) {
                    fprintf(stderr,
                            "dma_telem: disabling DMA telemetry after errors; "
                            "falling back to GPIO polling\n");
                    dma_telem_deinit();
                    use_dma = 0;
                    break;
                }
                usleep(10000);
                continue;
            }
            dma_errors = 0;

            vf_params_t p;
            vf_get_params(&p);
            uint8_t flags = (uint8_t)((p.enable & 0x01)
                           | ((hil_state == HIL_PAUSED) ? 0x02 : 0));
            for (int i = 0; i < n && telem_active; i++) {
                telem_push(dma_buf[i].t_cycles, dma_buf[i].epoch,
                           dma_buf[i].ialpha,
                           dma_buf[i].ibeta,
                           dma_buf[i].flux_alpha,
                           dma_buf[i].flux_beta,
                           dma_buf[i].speed,
                           flags);
            }
            /* PWM FIFO is drained by its own background thread (pwm_events_start);
             * one extra drain per burst (~1.28 ms @100 kHz) is cheap insurance
             * against the 2048-deep FIFO overflowing. Calling it per-sample was
             * the dominant PS overhead that capped the sustainable rate. */
            pwm_events_poll();
        }
    }

    if (!use_dma) {
        /* ── GPIO polling — read TIM_Solver monitors via /dev/mem ──────
         *
         * /dev/mem mapping for the AXI GPIO monitors is opened with O_SYNC,
         * so the mappings are uncached — every load goes to the device and
         * sees the value the FPGA wrote, no cache coherency issue (unlike
         * the AXI DMA HP-slave path).
         *
         * Pacing: clock_nanosleep(TIMER_ABSTIME) on CLOCK_MONOTONIC keeps the
         * deadline absolute - drift from one iteration does not cascade. The
         * rate is configurable via {"telem_hz":...}; Linux non-RT scheduling
         * adds jitter, so this is high-rate monitoring, not deterministic
         * capture of every solver step.
         */
        struct timespec next;
        clock_gettime(CLOCK_MONOTONIC, &next);

        while (running && telem_active) {
            next.tv_nsec += telem_period_ns();
            if (next.tv_nsec >= 1000000000L) {
                next.tv_sec += next.tv_nsec / 1000000000L;
                next.tv_nsec %= 1000000000L;
            }
            clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &next, NULL);

            vf_params_t p;
            vf_get_params(&p);
            uint8_t flags = (uint8_t)((p.enable & 0x01)
                           | ((hil_state == HIL_PAUSED) ? 0x02 : 0));

            telem_push(
                gpio_hil_time(), gpio_hil_epoch(),
                (float)gpio_get_ialpha()     * MON_SCALE,
                (float)gpio_get_ibeta()      * MON_SCALE,
                (float)gpio_get_flux_alpha() * MON_SCALE,
                (float)gpio_get_flux_beta()  * MON_SCALE,
                (float)gpio_get_speed()      * MON_SCALE,
                flags
            );
            pwm_events_poll();
        }
    }
    return NULL;
}

static void start_telem_thread(void)
{
    if (telem_active) return;
    telem_active = 1;
    pthread_create(&telem_tid, NULL, telem_thread_fn, NULL);
    pwm_events_start();
}

static void stop_telem_thread(void)
{
    if (!telem_active) return;
    telem_active = 0;
    pthread_join(telem_tid, NULL);
    telem_deinit();
    pwm_events_deinit();
}

/* Ensure telemetry is sending to the given IP (idempotent). */
static void ensure_telem_to(const char *ip)
{
    if (!ip || !*ip) return;
    if (strncmp(telem_dst_ip, ip, sizeof(telem_dst_ip)) == 0 && telem_active)
        return;

    stop_telem_thread();
    if (telem_init(ip) == 0) {
        if (pwm_events_init(ip) != 0)
            fprintf(stderr, "pwm_events: disabled for %s\n", ip);
        strncpy(telem_dst_ip, ip, sizeof(telem_dst_ip) - 1);
        telem_dst_ip[sizeof(telem_dst_ip) - 1] = '\0';
        start_telem_thread();
    }
}

/* ── State transitions ───────────────────────────────────────────────────── */

static void reset_solver_and_reprogram(void)
{
    vf_reset_solver();
    if (program_motor_coeffs(&motor_params) != 0)
        fprintf(stderr, "WARNING: failed to reprogram motor model after solver reset\n");
}

static void apply_run(void)
{
    /* Zera estados integradores/pipeline do solver antes de cada partida.
     * O reset completo tambem limpa coeficientes ativos, entao reprogramamos
     * o motor selecionado imediatamente apos liberar o reset. */
    reset_solver_and_reprogram();
    gpio_pwmcap_clear();

    vf_params_t p;
    vf_get_params(&p);
    p.enable = 1;
    vf_set_params(&p);
    hil_state = HIL_RUNNING;
}

static void apply_pause(void)
{
    vf_params_t p;
    vf_get_params(&p);
    p.enable = 0;
    vf_set_params(&p);
    hil_state = HIL_PAUSED;
}

/* Stop = motor off, params reset to safe defaults. Daemon stays alive. */
static void apply_stop(void)
{
    stop_telem_thread();
    telem_dst_ip[0] = '\0';

    vf_params_t p = {
        .freq_hz      = 0.0f,
        .vdc_v        = 1240.0f,
        .torque_nm    = 0.0f,
        .base_freq_hz = 60.0f,
        .max_v_pu     = 1.0f,
        .accel_time_s = 1.0f,
        .enable       = 0,
        .decim        = 0,
    };
    vf_set_params(&p);
    /* Zera os estados integradores para que monitor leituras imediatamente
     * apos o Stop reflitam o solver parado, nao o ultimo ponto operacional. */
    reset_solver_and_reprogram();
    hil_state = HIL_STOPPED;
}

/* ── UDP command helpers ─────────────────────────────────────────────────── */

/*
 * Protocol (JSON text). All responses include "state" so the client can sync.
 *
 *   SET:      {"cmd":"set","freq_hz":..,"vdc_v":..,"torque_nm":..,"decim":..,
 *               "telem_hz":..,"enable":0|1,"telem_dst":"<ip>"}
 *               ↳ all fields optional. "enable" forces state RUNNING/PAUSED.
 *               ↳ "telem_dst" configures/retargets telemetry push.
 *               ↳ "telem_hz" configures GPIO polling telemetry rate
 *                 (1000..50000 Hz, 0=default).
 *   MOTOR:    {"cmd":"motor","rs":..,"rr":..,"ls":..,"lr":..,"lm":..,"j":..,"npp":..}
 *               ↳ computes TIM matrices on PS and writes A/B/Y coefficients.
 *   GET:      {"cmd":"get"}
 *   RUN:      {"cmd":"run"}    — enable motor with current params
 *   PAUSE:    {"cmd":"pause"}  — disable motor, keep params
 *   STOP:     {"cmd":"stop"}   — disable motor, reset params (daemon stays)
 *   RESET:    {"cmd":"reset"}  — pulse solver_reset to zero integrator states,
 *                                keep params; FSM goes to PAUSED.
 *   TELEM:    {"cmd":"telem","dst":"<ip>"} — set telemetry destination
 *   SHUTDOWN: {"cmd":"shutdown"} — terminate daemon process
 *   PING:     {"cmd":"ping"}   — lightweight health check
 */

static int json_get_string(const char *buf, const char *key, char *out, size_t outsz)
{
    char pattern[64];
    snprintf(pattern, sizeof(pattern), "\"%s\":", key);
    const char *p = strstr(buf, pattern);
    if (!p) return 0;
    p = strchr(p + strlen(pattern), '"');
    if (!p) return 0;
    const char *end = strchr(p + 1, '"');
    if (!end) return 0;
    size_t len = (size_t)(end - p - 1);
    if (len >= outsz) len = outsz - 1;
    memcpy(out, p + 1, len);
    out[len] = '\0';
    return 1;
}

static int64_t q14_28(double v)
{
    const double scale = 268435456.0;
    const double max_v = (double)((1LL << 41) - 1) / scale;
    const double min_v = -(double)(1LL << 41) / scale;
    if (v > max_v) v = max_v;
    if (v < min_v) v = min_v;
    return (int64_t)llround(v * scale);
}


static void write_tim_coeff_shadow(uint32_t matrix, uint32_t row, uint32_t col, int64_t value)
{
    gpio_write_tim_coeff(matrix, row, col, value);
}

static int program_motor_coeffs(const motor_params_t *m)
{
    const double ts = 26.0 / 200000000.0;
    const double ls_total = (double)m->ls + (double)m->lm;
    const double lr_total = (double)m->lr + (double)m->lm;
    const double denom = (double)m->lm * (double)m->lm - ls_total * lr_total;
    if (fabs(denom) < 1e-12 || fabs(lr_total) < 1e-12 || fabs(m->j) < 1e-12)
        return -1;

    const double k = 1.0 / denom;
    const double a[5][5] = {
        { -ts*m->rr/lr_total, -ts*m->npp, ts*m->lm*m->rr/lr_total, 0.0, 0.0 },
        {  ts*m->npp, -ts*m->rr/lr_total, 0.0, ts*m->lm*m->rr/lr_total, 0.0 },
        { -ts*m->lm*m->rr*k/lr_total, -ts*m->lm*m->npp*k, ts*(m->lm*m->lm*m->rr*k/lr_total + lr_total*m->rs*k), 0.0, 0.0 },
        {  ts*m->lm*m->npp*k, -ts*m->lm*m->rr*k/lr_total, 0.0, ts*(m->lm*m->lm*m->rr*k/lr_total + lr_total*m->rs*k), 0.0 },
        {  ts*(3.0*m->npp*m->lm)/(2.0*m->j*lr_total), ts*(-3.0*m->npp*m->lm)/(2.0*m->j*lr_total), 0.0, 0.0, 0.0 },
    };
    const double b[5][3] = {
        { 0.0, 0.0, 0.0 },
        { 0.0, 0.0, 0.0 },
        { -ts*lr_total*k, 0.0, 0.0 },
        { 0.0, -ts*lr_total*k, 0.0 },
        { 0.0, 0.0, -ts/m->j },
    };

    for (uint32_t r = 0; r < 5; r++) {
        for (uint32_t c = 0; c < 5; c++) {
            write_tim_coeff_shadow(TIM_COEFF_MATRIX_A, r, c, q14_28(a[r][c]));
        }
        for (uint32_t c = 0; c < 3; c++)
            write_tim_coeff_shadow(TIM_COEFF_MATRIX_B, r, c, q14_28(b[r][c]));
    }
    gpio_apply_tim_coeffs();
    return 0;
}

static void build_status(char *resp, size_t sz, const char *status_msg)
{
    vf_params_t p;
    telem_stats_t ts;
    vf_get_params(&p);
    telem_stats(&ts);

    snprintf(resp, sz,
        "{\"status\":\"%s\","
        "\"state\":\"%s\","
        "\"ps_version\":\"%s\","
        "\"fpga_version\":%u,"
        "\"speed_rad_s\":%.4f,"
        "\"ialpha_A\":%.4f,"
        "\"ibeta_A\":%.4f,"
        "\"flux_alpha_Wb\":%.4f,"
        "\"flux_beta_Wb\":%.4f,"
        "\"freq_hz\":%.2f,"
        "\"freq_actual_hz\":%.2f,"
        "\"vdc_v\":%.2f,"
        "\"torque_nm\":%.4f,"
        "\"base_freq_hz\":%.2f,"
        "\"max_v_pu\":%.4f,"
        "\"accel_time_s\":%.2f,"
        "\"enable\":%d,"
        "\"telem_dst\":\"%s\","
        "\"telem_active\":%d,"
        "\"telem_source\":\"%s\","
        "\"telem_hz\":%u,"
        "\"telem_packets_sent\":%u,"
        "\"telem_send_errors\":%u}",
        status_msg,
        state_name(hil_state),
        PS_VERSION,
        gpio_fpga_version(),
        (float)gpio_get_speed()      * MON_SCALE,
        (float)gpio_get_ialpha()     * MON_SCALE,
        (float)gpio_get_ibeta()      * MON_SCALE,
        (float)gpio_get_flux_alpha() * MON_SCALE,
        (float)gpio_get_flux_beta()  * MON_SCALE,
        p.freq_hz, vf_get_freq_actual(),
        p.vdc_v, p.torque_nm,
        p.base_freq_hz, p.max_v_pu, p.accel_time_s,
        p.enable,
        telem_dst_ip,
        telem_active,
        telem_source_name(),
        telem_sample_hz,
        ts.packets_sent,
        ts.send_errors);
}

static void handle_packet(int sock, const char *buf,
                           struct sockaddr_in *cli, socklen_t cli_len)
{
    char resp[1024];
    const char *status_msg = "ok";

    if (strstr(buf, "\"cmd\":\"set\"")) {
        vf_params_t p;
        vf_get_params(&p);

        char *ptr;
        int explicit_enable = 0;
        int new_enable = p.enable;

        if ((ptr = strstr(buf, "\"freq_hz\":")))       sscanf(ptr + 10, "%f", &p.freq_hz);
        if ((ptr = strstr(buf, "\"vdc_v\":")))         sscanf(ptr + 8,  "%f", &p.vdc_v);
        if ((ptr = strstr(buf, "\"torque_nm\":")))     sscanf(ptr + 12, "%f", &p.torque_nm);
        if ((ptr = strstr(buf, "\"base_freq_hz\":")))  sscanf(ptr + 15, "%f", &p.base_freq_hz);
        if ((ptr = strstr(buf, "\"max_v_pu\":")))      sscanf(ptr + 11, "%f", &p.max_v_pu);
        if ((ptr = strstr(buf, "\"accel_time_s\":")))  sscanf(ptr + 15, "%f", &p.accel_time_s);
        if ((ptr = strstr(buf, "\"decim\":")))        { int d; sscanf(ptr + 8, "%d", &d); p.decim = d; }
        if ((ptr = strstr(buf, "\"telem_hz\":")))     { unsigned hz; sscanf(ptr + 11, "%u", &hz); set_telem_hz(hz); }
        if ((ptr = strstr(buf, "\"enable\":")))       { sscanf(ptr + 9, "%d", &new_enable); explicit_enable = 1; }

        if (explicit_enable) p.enable = new_enable ? 1 : 0;
        vf_set_params(&p);

        if (explicit_enable)
            hil_state = p.enable ? HIL_RUNNING : HIL_PAUSED;
        else if (hil_state == HIL_IDLE || hil_state == HIL_STOPPED)
            hil_state = HIL_PAUSED;  /* configured but not enabled yet */

        printf("[SET] freq=%.2fHz vdc=%.2fV torque=%.4fNm accel=%.1fs enable=%d telem=%uHz state=%s\n",
               p.freq_hz, p.vdc_v, p.torque_nm, p.accel_time_s, p.enable,
               telem_sample_hz, state_name(hil_state));

        /* Auto-configure telemetry destination if provided */
        char ip[INET_ADDRSTRLEN] = {0};
        if (json_get_string(buf, "telem_dst", ip, sizeof(ip)))
            ensure_telem_to(ip);

    } else if (strstr(buf, "\"cmd\":\"motor\"")) {
        motor_params_t m = motor_params;
        char *ptr;
        if ((ptr = strstr(buf, "\"rs\":")))  sscanf(ptr + 5, "%f", &m.rs);
        if ((ptr = strstr(buf, "\"rr\":")))  sscanf(ptr + 5, "%f", &m.rr);
        if ((ptr = strstr(buf, "\"ls\":")))  sscanf(ptr + 5, "%f", &m.ls);
        if ((ptr = strstr(buf, "\"lr\":")))  sscanf(ptr + 5, "%f", &m.lr);
        if ((ptr = strstr(buf, "\"lm\":")))  sscanf(ptr + 5, "%f", &m.lm);
        if ((ptr = strstr(buf, "\"j\":")))   sscanf(ptr + 4, "%f", &m.j);
        if ((ptr = strstr(buf, "\"npp\":"))) sscanf(ptr + 6, "%f", &m.npp);

        if (program_motor_coeffs(&m) == 0) {
            motor_params = m;
            if (hil_state == HIL_IDLE || hil_state == HIL_STOPPED)
                hil_state = HIL_PAUSED;
            status_msg = "motor_model_applied_atomic";
            printf("[MOTOR] rs=%.6g rr=%.6g ls=%.6g lr=%.6g lm=%.6g j=%.6g npp=%.3g\n",
                   m.rs, m.rr, m.ls, m.lr, m.lm, m.j, m.npp);
        } else {
            status_msg = "invalid_motor_params";
        }


    } else if (strstr(buf, "\"cmd\":\"get\"")) {
        /* fall through to send status */

    } else if (strstr(buf, "\"cmd\":\"run\"")) {
        apply_run();
        printf("[RUN] state=%s\n", state_name(hil_state));

    } else if (strstr(buf, "\"cmd\":\"pause\"")) {
        apply_pause();
        printf("[PAUSE] state=%s\n", state_name(hil_state));

    } else if (strstr(buf, "\"cmd\":\"stop\"")) {
        apply_stop();
        printf("[STOP] state=%s (daemon alive)\n", state_name(hil_state));

    } else if (strstr(buf, "\"cmd\":\"reset\"")) {
        reset_solver_and_reprogram();
        hil_state = HIL_PAUSED;
        /* Reset leaves params intact but motor disabled - same posture as Pause. */
        printf("[RESET] solver states cleared, state=%s\n", state_name(hil_state));

    } else if (strstr(buf, "\"cmd\":\"telem\"")) {
        char ip[INET_ADDRSTRLEN] = {0};
        if (json_get_string(buf, "dst", ip, sizeof(ip))) {
            if (ip[0] == '\0' || strcmp(ip, "off") == 0 || strcmp(ip, "stop") == 0) {
                stop_telem_thread();
                telem_dst_ip[0] = '\0';
                printf("[TELEM] stopped active=%d\n", telem_active);
            } else {
                ensure_telem_to(ip);
                printf("[TELEM] dst=%s active=%d\n", telem_dst_ip, telem_active);
            }
        } else {
            status_msg = "missing_dst";
        }

    } else if (strstr(buf, "\"cmd\":\"ping\"")) {
        /* lightweight; just answer with current status */

    } else if (strstr(buf, "\"cmd\":\"shutdown\"")) {
        apply_stop();
        printf("[SHUTDOWN] daemon will exit\n");
        build_status(resp, sizeof(resp), "shutting_down");
        sendto(sock, resp, strlen(resp), 0, (struct sockaddr *)cli, cli_len);
        running = 0;
        return;

    } else {
        status_msg = "unknown_command";
    }

    build_status(resp, sizeof(resp), status_msg);
    sendto(sock, resp, strlen(resp), 0, (struct sockaddr *)cli, cli_len);
}

/* ── Discovery responder ─────────────────────────────────────────────────── */

/* Pick first non-loopback IPv4 + its MAC. Returns 0 on success. */
static int local_iface_info(char *ip_out, size_t ip_sz, char *mac_out, size_t mac_sz)
{
    struct ifaddrs *ifap = NULL, *ifa;
    if (getifaddrs(&ifap) != 0) return -1;

    char chosen_iface[IFNAMSIZ] = {0};
    int  found_ip = 0;

    for (ifa = ifap; ifa; ifa = ifa->ifa_next) {
        if (!ifa->ifa_addr) continue;
        if (ifa->ifa_addr->sa_family != AF_INET) continue;
        if (ifa->ifa_flags & IFF_LOOPBACK) continue;
        struct sockaddr_in *sa = (struct sockaddr_in *)ifa->ifa_addr;
        if (inet_ntop(AF_INET, &sa->sin_addr, ip_out, ip_sz)) {
            snprintf(chosen_iface, sizeof(chosen_iface), "%s", ifa->ifa_name);
            found_ip = 1;
            break;
        }
    }
    freeifaddrs(ifap);
    if (!found_ip) return -1;

    /* Pull MAC via ioctl */
    int s = socket(AF_INET, SOCK_DGRAM, 0);
    if (s < 0) return -1;
    struct ifreq ifr = {0};
    snprintf(ifr.ifr_name, sizeof(ifr.ifr_name), "%s", chosen_iface);
    if (ioctl(s, SIOCGIFHWADDR, &ifr) == 0) {
        unsigned char *h = (unsigned char *)ifr.ifr_hwaddr.sa_data;
        snprintf(mac_out, mac_sz, "%02x:%02x:%02x:%02x:%02x:%02x",
                 h[0], h[1], h[2], h[3], h[4], h[5]);
    } else {
        snprintf(mac_out, mac_sz, "00:00:00:00:00:00");
    }
    close(s);
    return 0;
}

static pthread_t disc_tid;
static volatile int disc_active = 0;
static int disc_sock = -1;

static void *discovery_thread_fn(void *arg)
{
    (void)arg;
    sigset_t set;
    sigemptyset(&set);
    sigaddset(&set, SIGRTMIN);
    pthread_sigmask(SIG_BLOCK, &set, NULL);

    char buf[256];
    char my_ip[INET_ADDRSTRLEN] = "0.0.0.0";
    char my_mac[32]            = "00:00:00:00:00:00";
    local_iface_info(my_ip, sizeof(my_ip), my_mac, sizeof(my_mac));

    while (running && disc_active) {
        struct sockaddr_in cli;
        socklen_t cli_len = sizeof(cli);
        ssize_t n = recvfrom(disc_sock, buf, sizeof(buf) - 1, 0,
                             (struct sockaddr *)&cli, &cli_len);
        if (n <= 0) continue;
        buf[n] = '\0';
        if (strstr(buf, DISCOVERY_MAGIC) == NULL) continue;

        char resp[384];
        int len = snprintf(resp, sizeof(resp),
            "{\"type\":\"hil_discovery\","
            "\"name\":\"%s\","
            "\"ip\":\"%s\","
            "\"mac\":\"%s\","
            "\"cmd_port\":%d,"
            "\"telem_port\":%d,"
            "\"state\":\"%s\"}",
            BOARD_NAME, my_ip, my_mac,
            UDP_PORT, TELEM_PORT, state_name(hil_state));
        sendto(disc_sock, resp, (size_t)len, 0,
               (struct sockaddr *)&cli, cli_len);
    }
    return NULL;
}

static int start_discovery(void)
{
    disc_sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (disc_sock < 0) { perror("disc socket"); return -1; }

    set_udp_reuse(disc_sock);
    int yes = 1;
    setsockopt(disc_sock, SOL_SOCKET, SO_BROADCAST, &yes, sizeof(yes));

    struct sockaddr_in addr = {
        .sin_family      = AF_INET,
        .sin_port        = htons(DISCOVERY_PORT),
        .sin_addr.s_addr = INADDR_ANY,
    };
    if (bind(disc_sock, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("disc bind"); close(disc_sock); disc_sock = -1; return -1;
    }
    struct timeval tv = { .tv_sec = 0, .tv_usec = 200000 };
    setsockopt(disc_sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

    disc_active = 1;
    pthread_create(&disc_tid, NULL, discovery_thread_fn, NULL);
    return 0;
}

static void stop_discovery(void)
{
    if (!disc_active) return;
    disc_active = 0;
    pthread_join(disc_tid, NULL);
    if (disc_sock >= 0) { close(disc_sock); disc_sock = -1; }
}

/* ── main ─────────────────────────────────────────────────────────────────── */

static void sigint_handler(int s) { (void)s; running = 0; }

int main(void)
{
    setbuf(stdout, NULL);  /* flush imediato via pipe SSH */

    signal(SIGINT,  sigint_handler);
    signal(SIGTERM, sigint_handler);

    printf("HIL Controller starting...\n");

    /* Single-instance guard. Two hil_controller instances both driving the
     * FPGA at 1 kHz produce conflicting pwm_ctrl writes (enable toggles →
     * pwm_cap_epoch spins → telemetry timeline never advances, and state
     * oscillates running/paused as command responses load-balance between
     * them). An exclusive flock guarantees exactly one instance: a second
     * one exits immediately. The lock auto-releases when the process dies,
     * so the inittab respawn always succeeds. This is independent of UDP
     * socket options (SO_REUSEADDR alone still permits duplicate binds). */
    {
        int lock_fd = open("/tmp/hil_controller.lock", O_CREAT | O_RDWR, 0644);
        if (lock_fd < 0 || flock(lock_fd, LOCK_EX | LOCK_NB) < 0) {
            fprintf(stderr, "hil_controller: another instance is already "
                            "running — exiting.\n");
            return 1;
        }
        /* lock_fd intentionally leaked — held for the process lifetime. */
    }

    if (gpio_init() < 0)  return 1;
    if (vf_init()   < 0)  return 1;

    /* Program the default motor model into the solver at startup. A fresh
     * bitstream (loaded by FSBL on every power-on) comes up with no TIM
     * coefficients, so without this the solver outputs zeros until the user
     * clicks "Apply Motor". Programming the defaults here makes the board
     * produce correct dynamics immediately after power-on — no manual step. */
    if (program_motor_coeffs(&motor_params) == 0)
        printf("Motor model programmed at startup (default params)\n");
    else
        fprintf(stderr, "WARNING: failed to program default motor model at startup\n");

    if (setup_vf_timer() < 0) return 1;

    if (dma_telem_init() == 0) {
        use_dma = 1;
        printf("Telemetry: DMA S2MM -> reserved DDR enabled (fallback GPIO %u..%u Hz)\n",
               TELEM_MIN_HZ, TELEM_MAX_GPIO_HZ);
    } else {
        use_dma = 0;
        fprintf(stderr, "Telemetry: DMA unavailable; falling back to GPIO polling default %u Hz\n",
                TELEM_DEFAULT_HZ);
    }

    int sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (sock < 0) { perror("socket"); return 1; }
    set_udp_reuse(sock);

    struct sockaddr_in addr = {
        .sin_family      = AF_INET,
        .sin_port        = htons(UDP_PORT),
        .sin_addr.s_addr = INADDR_ANY,
    };
    if (bind(sock, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("bind"); return 1;
    }

    struct timeval tv = { .tv_sec = 0, .tv_usec = 100000 };
    setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

    /* Drain any stale datagrams that accumulated while the process was stopped
     * (e.g. from a gateway subnet scan). Without this, old pings queue up and
     * block real commands for seconds after each restart. */
    {
        int fl = fcntl(sock, F_GETFL, 0);
        fcntl(sock, F_SETFL, fl | O_NONBLOCK);
        char drain[512];
        int drained = 0;
        while (recv(sock, drain, sizeof(drain), 0) > 0) drained++;
        if (drained) printf("Drained %d stale datagrams from cmd socket.\n", drained);
        fcntl(sock, F_SETFL, fl);
    }

    if (start_discovery() == 0)
        printf("Discovery responder on UDP port %d\n", DISCOVERY_PORT);
    else
        fprintf(stderr, "Discovery responder failed to start (continuing).\n");

    printf("Listening on UDP port %d\n", UDP_PORT);
    printf("Telemetry push port: %d  (burst=%d samples)\n", TELEM_PORT, TELEM_BURST);
    printf("Commands: set / get / run / pause / stop / reset / telem / ping / shutdown\n\n");

    char buf[512];
    while (running) {
        struct sockaddr_in cli;
        socklen_t cli_len = sizeof(cli);
        ssize_t n = recvfrom(sock, buf, sizeof(buf) - 1, 0,
                             (struct sockaddr *)&cli, &cli_len);
        if (n > 0) {
            buf[n] = '\0';
            handle_packet(sock, buf, &cli, cli_len);
        }
    }

    printf("Shutting down...\n");
    stop_discovery();
    cancel_timer();
    stop_telem_thread();
    if (use_dma) dma_telem_deinit();
    vf_deinit();
    gpio_deinit();
    close(sock);
    return 0;
}
