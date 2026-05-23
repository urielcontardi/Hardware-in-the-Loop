#include "gpio.h"
#include "vf_ctrl.h"
#include "telemetry.h"
#include "dma_telem.h"

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
    .rs = 0.4396f,
    .rr = 0.2826f,
    .ls = 3.1364e-3f,
    .lr = 6.3264e-3f,
    .lm = 109.9442e-3f,
    .j = 0.4f,
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

/* ── 1 kHz POSIX timer (vf_tick) ─────────────────────────────────────────── */

static void timer_handler(int sig, siginfo_t *si, void *uc)
{
    (void)sig; (void)si; (void)uc;
    vf_tick();
}

static timer_t g_timerid;

static void set_udp_reuse(int sock)
{
    int yes = 1;
    setsockopt(sock, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));
#ifdef SO_REUSEPORT
    setsockopt(sock, SOL_SOCKET, SO_REUSEPORT, &yes, sizeof(yes));
#endif
}

static int setup_1khz_timer(void)
{
    struct sigaction sa = {
        .sa_sigaction = timer_handler,
        .sa_flags     = SA_SIGINFO,
    };
    sigemptyset(&sa.sa_mask);
    if (sigaction(SIGRTMIN, &sa, NULL) < 0) { perror("sigaction"); return -1; }

    struct sigevent sev = {
        .sigev_notify = SIGEV_SIGNAL,
        .sigev_signo  = SIGRTMIN,
    };
    if (timer_create(CLOCK_MONOTONIC, &sev, &g_timerid) < 0) {
        perror("timer_create"); return -1;
    }

    struct itimerspec its = {
        .it_value    = { .tv_sec = 0, .tv_nsec = 1000000 },
        .it_interval = { .tv_sec = 0, .tv_nsec = 1000000 },
    };
    if (timer_settime(g_timerid, 0, &its, NULL) < 0) {
        perror("timer_settime"); return -1;
    }
    return 0;
}

static void cancel_timer(void)
{
    struct itimerspec zero = {0};
    timer_settime(g_timerid, 0, &zero, NULL);
    timer_delete(g_timerid);
}

/* ── Telemetry thread — reads gpio at 1 kHz, pushes bursts ──────────────── */

static pthread_t telem_tid;
static volatile int telem_active = 0;

/*
 * DMA telemetry thread — transfers DMA_BURST_FRAMES samples per DMA call,
 * then pushes each sample through the UDP telemetry path. Falls back to
 * the legacy GPIO-polling path if DMA init fails.
 *
 * Rate:
 *   DMA burst = DMA_BURST_FRAMES at ~10 kHz.
 *   Each DMA sample is forwarded through the existing UDP telemetry path.
 */
static int use_dma = 0;    /* set to 1 if DMA init succeeds */

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
            if (n <= 0) {
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
                telem_push(dma_buf[i].ialpha,
                           dma_buf[i].ibeta,
                           dma_buf[i].flux_alpha,
                           dma_buf[i].flux_beta,
                           dma_buf[i].speed,
                           flags);
            }
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
         * Pacing: clock_nanosleep(TIMER_ABSTIME) on CLOCK_MONOTONIC keeps
         * the deadline absolute — drift from one iteration doesn't cascade.
         * Target period 100 µs (10 kHz). Linux non-RT scheduler will jitter
         * by tens of µs, but the *average* rate stays at 10 kHz over time.
         */
        const long period_ns = 100000L;  /* 100 µs → 10 kHz */
        struct timespec next;
        clock_gettime(CLOCK_MONOTONIC, &next);

        while (running && telem_active) {
            next.tv_nsec += period_ns;
            if (next.tv_nsec >= 1000000000L) {
                next.tv_nsec -= 1000000000L;
                next.tv_sec  += 1;
            }
            clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &next, NULL);

            vf_params_t p;
            vf_get_params(&p);
            uint8_t flags = (uint8_t)((p.enable & 0x01)
                           | ((hil_state == HIL_PAUSED) ? 0x02 : 0));

            telem_push(
                (float)gpio_get_ialpha()     * MON_SCALE,
                (float)gpio_get_ibeta()      * MON_SCALE,
                (float)gpio_get_flux_alpha() * MON_SCALE,
                (float)gpio_get_flux_beta()  * MON_SCALE,
                (float)gpio_get_speed()      * MON_SCALE,
                flags
            );
        }
    }
    return NULL;
}

static void start_telem_thread(void)
{
    if (telem_active) return;
    telem_active = 1;
    pthread_create(&telem_tid, NULL, telem_thread_fn, NULL);
}

static void stop_telem_thread(void)
{
    if (!telem_active) return;
    telem_active = 0;
    pthread_join(telem_tid, NULL);
    telem_deinit();
}

/* Ensure telemetry is sending to the given IP (idempotent). */
static void ensure_telem_to(const char *ip)
{
    if (!ip || !*ip) return;
    if (strncmp(telem_dst_ip, ip, sizeof(telem_dst_ip)) == 0 && telem_active)
        return;

    stop_telem_thread();
    if (telem_init(ip) == 0) {
        strncpy(telem_dst_ip, ip, sizeof(telem_dst_ip) - 1);
        telem_dst_ip[sizeof(telem_dst_ip) - 1] = '\0';
        start_telem_thread();
    }
}

/* ── State transitions ───────────────────────────────────────────────────── */

static void apply_run(void)
{
    /* Zera estados integradores do solver antes de cada partida — caso
     * contrário fluxos/correntes do run anterior podem mascarar a nova
     * excitação (constantes de tempo do rotor podem ser de segundos). */
    vf_reset_solver();

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
     * após o Stop reflitam o solver parado, não o último ponto operacional. */
    vf_reset_solver();
    hil_state = HIL_STOPPED;
}

/* ── UDP command helpers ─────────────────────────────────────────────────── */

/*
 * Protocol (JSON text). All responses include "state" so the client can sync.
 *
 *   SET:      {"cmd":"set","freq_hz":..,"vdc_v":..,"torque_nm":..,"decim":..,
 *               "enable":0|1,"telem_dst":"<ip>"}
 *               ↳ all fields optional. "enable" forces state RUNNING/PAUSED.
 *               ↳ "telem_dst" configures/retargets telemetry push.
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

static int64_t y_entry(int idx)
{
    return idx < 0 ? (int64_t)(1ULL << 41) : (int64_t)idx;
}

static void wait_solver_idle(void)
{
    for (int i = 0; i < 100000; i++) {
        uint32_t st = gpio_read(ADDR_HIL_REGS, REG_DEBUG_STATUS);
        if (((st >> 6) & 1U) == 0) return;
        if ((i & 0x3f) == 0) usleep(1);
    }
}

static void write_tim_coeff_when_idle(uint32_t matrix, uint32_t row, uint32_t col, int64_t value)
{
    wait_solver_idle();
    gpio_write_tim_coeff(matrix, row, col, value);
}


static int program_motor_coeffs(const motor_params_t *m)
{
    const double ts = 27.0 / 100000000.0;
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
    const int y[5][5] = {
        { -1,  4, -1, -1, -1 },
        {  4, -1, -1, -1, -1 },
        { -1,  4, -1, -1, -1 },
        {  4, -1, -1, -1, -1 },
        {  3,  2, -1, -1, -1 },
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
            write_tim_coeff_when_idle(TIM_COEFF_MATRIX_A, r, c, q14_28(a[r][c]));
            write_tim_coeff_when_idle(TIM_COEFF_MATRIX_Y, r, c, y_entry(y[r][c]));
        }
        for (uint32_t c = 0; c < 3; c++)
            write_tim_coeff_when_idle(TIM_COEFF_MATRIX_B, r, c, q14_28(b[r][c]));
    }
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
        "\"telem_packets_sent\":%u,"
        "\"telem_send_errors\":%u}",
        status_msg,
        state_name(hil_state),
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
        ts.packets_sent,
        ts.send_errors);
}

static void handle_packet(int sock, const char *buf,
                           struct sockaddr_in *cli, socklen_t cli_len)
{
    char resp[768];
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
        if ((ptr = strstr(buf, "\"enable\":")))       { sscanf(ptr + 9, "%d", &new_enable); explicit_enable = 1; }

        if (explicit_enable) p.enable = new_enable ? 1 : 0;
        vf_set_params(&p);

        if (explicit_enable)
            hil_state = p.enable ? HIL_RUNNING : HIL_PAUSED;
        else if (hil_state == HIL_IDLE || hil_state == HIL_STOPPED)
            hil_state = HIL_PAUSED;  /* configured but not enabled yet */

        printf("[SET] freq=%.2fHz vdc=%.2fV torque=%.4fNm accel=%.1fs enable=%d state=%s\n",
               p.freq_hz, p.vdc_v, p.torque_nm, p.accel_time_s, p.enable, state_name(hil_state));

        /* Auto-configure telemetry destination if provided */
        char ip[INET_ADDRSTRLEN] = {0};
        if (json_get_string(buf, "telem_dst", ip, sizeof(ip)))
            ensure_telem_to(ip);

    } else if (strstr(buf, "\"cmd\":\"motor\"")) {
        if (hil_state == HIL_RUNNING) {
            status_msg = "motor_update_requires_pause";
            goto send_response;
        }

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
            vf_reset_solver();
            if (hil_state == HIL_IDLE || hil_state == HIL_STOPPED)
                hil_state = HIL_PAUSED;
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
        vf_reset_solver();
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

send_response:
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

    if (gpio_init() < 0)  return 1;
    if (vf_init()   < 0)  return 1;
    if (setup_1khz_timer() < 0) return 1;

    /* DIAGNOSTIC: forcibly disable DMA to isolate cache-coherency bug.
     * AXI DMA HP-slave path is NOT cache-coherent with Cortex-A9; userspace
     * lacks the D-cache invalidate operation needed before each buffer read.
     * GPIO polling reads via /dev/mem with O_SYNC (uncached) and is provably
     * coherent. If signals come back clean on this fallback, the bug is in
     * dma_telem coherency and the proper fix is to re-route AXI DMA to
     * S_AXI_ACP in the Vivado design (cache-coherent port) or to use a
     * kernel module that exposes a D-cache invalidate ioctl. */
    use_dma = 0;
    printf("Telemetry: GPIO polling 10 kHz (DMA disabled for coherency)\n");
    (void)0; /* dma_telem_init not called */

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
