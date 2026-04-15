#include "gpio.h"
#include "vf_ctrl.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <time.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <math.h>

/* UDP server port */
#define UDP_PORT  5005

/* Monitor scale: 32 MSBs of Q14.28 → divide by 2^18 to get float */
#define MON_SCALE  (1.0f / (float)(1 << 18))

/* Vdc scale: Q31 → V (same VDC_MAX_V as vf_ctrl.c) */
#define VDC_MAX_V     600.0f
#define TORQUE_MAX_NM  50.0f

static volatile int running = 1;

/* ---------- 1 kHz timer via POSIX timer ---------- */

static void timer_handler(int sig, siginfo_t *si, void *uc)
{
    (void)sig; (void)si; (void)uc;
    vf_tick();
}

static int setup_1khz_timer(void)
{
    struct sigaction sa = {
        .sa_sigaction = timer_handler,
        .sa_flags     = SA_SIGINFO,
    };
    sigemptyset(&sa.sa_mask);
    if (sigaction(SIGRTMIN, &sa, NULL) < 0) {
        perror("sigaction");
        return -1;
    }

    struct sigevent sev = {
        .sigev_notify = SIGEV_SIGNAL,
        .sigev_signo  = SIGRTMIN,
    };
    timer_t timerid;
    if (timer_create(CLOCK_MONOTONIC, &sev, &timerid) < 0) {
        perror("timer_create");
        return -1;
    }

    struct itimerspec its = {
        .it_value    = { .tv_sec = 0, .tv_nsec = 1000000 }, /* 1 ms */
        .it_interval = { .tv_sec = 0, .tv_nsec = 1000000 },
    };
    if (timer_settime(timerid, 0, &its, NULL) < 0) {
        perror("timer_settime");
        return -1;
    }
    return 0;
}

/* ---------- UDP helpers ---------- */

/*
 * Protocol (JSON text):
 *
 *   POST:  {"cmd":"set","freq_hz":30.0,"vdc_v":300.0,"torque_nm":0.0,"enable":1,"decim":0}
 *   GET:   {"cmd":"get"}
 *   STOP:  {"cmd":"stop"}
 *
 *   Response to GET:
 *   {"speed_rad_s":..., "ialpha_A":..., "ibeta_A":...,
 *    "flux_alpha_Wb":..., "flux_beta_Wb":...,
 *    "freq_hz":..., "enable":...}
 */

static float mon_to_float(int32_t raw) { return (float)raw * MON_SCALE; }

static void handle_packet(int sock, const char *buf, ssize_t len,
                           struct sockaddr_in *cli, socklen_t cli_len)
{
    char resp[512];

    /* Very simple JSON parser — looks for key:value pairs */
    if (strstr(buf, "\"cmd\":\"set\"")) {
        vf_params_t p;
        vf_get_params(&p);

        /* Parse each field if present */
        char *ptr;
        if ((ptr = strstr(buf, "\"freq_hz\":")))   sscanf(ptr + 9,  "%f", &p.freq_hz);
        if ((ptr = strstr(buf, "\"vdc_v\":")))      sscanf(ptr + 8,  "%f", &p.vdc_v);
        if ((ptr = strstr(buf, "\"torque_nm\":")))  sscanf(ptr + 12, "%f", &p.torque_nm);
        if ((ptr = strstr(buf, "\"enable\":")))     { int e; sscanf(ptr + 9, "%d", &e); p.enable = e; }
        if ((ptr = strstr(buf, "\"decim\":")))      { int d; sscanf(ptr + 8, "%d", &d); p.decim  = d; }

        vf_set_params(&p);
        snprintf(resp, sizeof(resp), "{\"status\":\"ok\"}");

    } else if (strstr(buf, "\"cmd\":\"get\"")) {
        float speed      = mon_to_float(gpio_get_speed());
        float ialpha     = mon_to_float(gpio_get_ialpha());
        float ibeta      = mon_to_float(gpio_get_ibeta());
        float flux_alpha = mon_to_float(gpio_get_flux_alpha());
        float flux_beta  = mon_to_float(gpio_get_flux_beta());

        vf_params_t p;
        vf_get_params(&p);

        snprintf(resp, sizeof(resp),
            "{\"speed_rad_s\":%.4f,"
            "\"ialpha_A\":%.4f,"
            "\"ibeta_A\":%.4f,"
            "\"flux_alpha_Wb\":%.4f,"
            "\"flux_beta_Wb\":%.4f,"
            "\"freq_hz\":%.2f,"
            "\"vdc_v\":%.2f,"
            "\"enable\":%d}",
            speed, ialpha, ibeta, flux_alpha, flux_beta,
            p.freq_hz, p.vdc_v, p.enable);

    } else if (strstr(buf, "\"cmd\":\"stop\"")) {
        running = 0;
        snprintf(resp, sizeof(resp), "{\"status\":\"stopping\"}");

    } else {
        snprintf(resp, sizeof(resp), "{\"error\":\"unknown command\"}");
    }

    sendto(sock, resp, strlen(resp), 0,
           (struct sockaddr *)cli, cli_len);
}

/* ---------- main ---------- */

static void sigint_handler(int s) { (void)s; running = 0; }

int main(void)
{
    signal(SIGINT,  sigint_handler);
    signal(SIGTERM, sigint_handler);

    printf("HIL Controller starting...\n");

    if (gpio_init() < 0)  return 1;
    if (vf_init()   < 0)  return 1;

    if (setup_1khz_timer() < 0) return 1;

    /* UDP socket */
    int sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (sock < 0) { perror("socket"); return 1; }

    struct sockaddr_in addr = {
        .sin_family      = AF_INET,
        .sin_port        = htons(UDP_PORT),
        .sin_addr.s_addr = INADDR_ANY,
    };
    if (bind(sock, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("bind"); return 1;
    }

    /* non-blocking with 100 ms timeout */
    struct timeval tv = { .tv_sec = 0, .tv_usec = 100000 };
    setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

    printf("Listening on UDP port %d\n", UDP_PORT);
    printf("Commands: {\"cmd\":\"set\",\"freq_hz\":30,\"vdc_v\":300,\"enable\":1}\n");
    printf("          {\"cmd\":\"get\"}\n");
    printf("          {\"cmd\":\"stop\"}\n\n");

    char buf[512];
    while (running) {
        struct sockaddr_in cli;
        socklen_t cli_len = sizeof(cli);
        ssize_t n = recvfrom(sock, buf, sizeof(buf) - 1, 0,
                             (struct sockaddr *)&cli, &cli_len);
        if (n > 0) {
            buf[n] = '\0';
            handle_packet(sock, buf, n, &cli, cli_len);
        }
    }

    printf("Shutting down...\n");
    vf_deinit();
    gpio_deinit();
    close(sock);
    return 0;
}
