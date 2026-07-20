#include "pwm_events.h"
#include "gpio.h"

#include <arpa/inet.h>
#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>

#define PWM_EVENTS_PER_PACKET 96
#define PWM_JSON_MAX 8192

static int sock = -1;
static struct sockaddr_in dest_addr;
static pthread_t tid;
static volatile int active = 0;
static uint32_t seq = 0;

static void set_udp_reuse(int fd)
{
    int yes = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));
#ifdef SO_REUSEPORT
    setsockopt(fd, SOL_SOCKET, SO_REUSEPORT, &yes, sizeof(yes));
#endif
}

static void send_events(uint64_t *events, int n, uint32_t status)
{
    if (sock < 0 || n <= 0) return;

    char json[PWM_JSON_MAX];
    int pos = snprintf(json, sizeof(json),
        "{\"type\":\"pwm_events\",\"seq\":%u,\"clock_hz\":%u,\"status\":%u,\"events\":[",
        seq++, PWM_EVENTS_CLOCK_HZ, status);

    for (int i = 0; i < n && pos > 0 && pos < (int)sizeof(json); i++) {
        uint64_t e = events[i];
        uint32_t t = (uint32_t)(e & 0xffffffffULL);
        uint8_t a = (uint8_t)((e >> 32) & 0xfU);
        uint8_t b = (uint8_t)((e >> 36) & 0xfU);
        uint8_t c = (uint8_t)((e >> 40) & 0xfU);
        uint8_t mask = (uint8_t)((e >> 44) & 0xfU);
        uint16_t epoch = (uint16_t)((e >> 48) & 0xffffU);
        pos += snprintf(json + pos, sizeof(json) - (size_t)pos,
                        "%s[%u,%u,%u,%u,%u,%u]",
                        i ? "," : "", t, a, b, c, mask, epoch);
    }
    /* snprintf reports what it *would* have written, so an overflowing batch
     * used to silently drop all n events instead of the tail that did not fit. */
    if (pos <= 0) return;
    if (pos >= (int)sizeof(json)) {
        fprintf(stderr, "pwm_events: JSON overflow, %d event(s) dropped\n", n);
        return;
    }
    pos += snprintf(json + pos, sizeof(json) - (size_t)pos, "]}");
    if (pos <= 0 || pos >= (int)sizeof(json)) return;

    (void)sendto(sock, json, (size_t)pos, 0,
                 (struct sockaddr *)&dest_addr, sizeof(dest_addr));
}

/* Two threads drain this FIFO: thread_fn() below, and the telemetry thread via
 * pwm_events_poll(). gpio_pwmcap_read() is a non-atomic status/peek/pop
 * sequence, so without this lock both could clear the empty flag, peek the same
 * entry, and then pop twice -- reporting one event twice and consuming the next
 * one without ever reading it. A lost event is the damaging half: when it is a
 * dead-time exit, the offline replay leaves that leg parked at +-Vdc/4 for the
 * rest of the carrier period. The duplicates are the visible tell (a
 * change-triggered FIFO cannot emit two identical consecutive events), and they
 * land in different UDP packets because each thread sends its own. seq is
 * incremented under the same lock, since two senders racing on it is what put
 * packets on the wire out of order. */
static pthread_mutex_t drain_mu = PTHREAD_MUTEX_INITIALIZER;

static int drain_once(void)
{
    uint64_t batch[PWM_EVENTS_PER_PACKET];
    int n = 0;

    pthread_mutex_lock(&drain_mu);
    uint32_t status = gpio_pwmcap_status();
    while (n < PWM_EVENTS_PER_PACKET && gpio_pwmcap_read(&batch[n])) {
        n++;
    }
    if (n > 0) {
        send_events(batch, n, status);
    }
    pthread_mutex_unlock(&drain_mu);
    return n;
}

static void *thread_fn(void *arg)
{
    (void)arg;
    while (active) {
        if (drain_once() == 0) usleep(500);
    }
    return NULL;
}

void pwm_events_poll(void)
{
    if (!active || sock < 0) return;
    (void)drain_once();
}

int pwm_events_init(const char *dest_ip)
{
    if (sock >= 0) { close(sock); sock = -1; }
    sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (sock < 0) { perror("pwm_events: socket"); return -1; }
    set_udp_reuse(sock);

    struct sockaddr_in local_addr;
    memset(&local_addr, 0, sizeof(local_addr));
    local_addr.sin_family = AF_INET;
    local_addr.sin_addr.s_addr = htonl(INADDR_ANY);
    local_addr.sin_port = htons(PWM_EVENTS_PORT);
    if (bind(sock, (struct sockaddr *)&local_addr, sizeof(local_addr)) != 0) {
        perror("pwm_events: bind");
        close(sock); sock = -1; return -1;
    }

    memset(&dest_addr, 0, sizeof(dest_addr));
    dest_addr.sin_family = AF_INET;
    dest_addr.sin_port = htons(PWM_EVENTS_PORT);
    if (inet_pton(AF_INET, dest_ip, &dest_addr.sin_addr) != 1) {
        fprintf(stderr, "pwm_events: invalid IP %s\n", dest_ip);
        close(sock); sock = -1; return -1;
    }

    seq = 0;
    gpio_pwmcap_set_window(0);
    gpio_pwmcap_clear();
    printf("pwm_events -> %s:%d\n", dest_ip, PWM_EVENTS_PORT);
    return 0;
}

void pwm_events_start(void)
{
    if (active || sock < 0) return;
    active = 1;
    pthread_create(&tid, NULL, thread_fn, NULL);
}

void pwm_events_stop(void)
{
    if (!active) return;
    active = 0;
    pthread_join(tid, NULL);
}

void pwm_events_deinit(void)
{
    pwm_events_stop();
    if (sock >= 0) { close(sock); sock = -1; }
}
