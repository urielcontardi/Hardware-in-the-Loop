#include "telemetry.h"

#include <arpa/inet.h>
#include <string.h>
#include <stdio.h>
#include <unistd.h>
#include <sys/socket.h>

/* ── CRC-16/CCITT-FALSE  poly=0x1021  init=0xFFFF ───────────────────────── */
static uint16_t crc16(const uint8_t *data, size_t len)
{
    uint16_t crc = 0xFFFFu;
    for (size_t i = 0; i < len; i++) {
        crc ^= (uint16_t)data[i] << 8;
        for (int j = 0; j < 8; j++)
            crc = (crc & 0x8000u) ? (uint16_t)((crc << 1) ^ 0x1021u)
                                  : (uint16_t)(crc << 1);
    }
    return crc;
}

/* ── Internal state ──────────────────────────────────────────────────────── */
#define HDR_SIZE    10u
#define SAMPLE_BYTES 20u   /* 5 × float32 */
#define MAX_FRAME   (HDR_SIZE + TELEM_BURST * SAMPLE_BYTES + 2u)

static int               sock       = -1;
static struct sockaddr_in dest_addr;
static uint32_t          seq        = 0;
static telem_sample_t    burst[TELEM_BURST];
static int               burst_idx  = 0;
static uint8_t           last_flags = 0;

/* ── Public API ──────────────────────────────────────────────────────────── */

int telem_init(const char *dest_ip)
{
    if (sock >= 0) { close(sock); sock = -1; }

    sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (sock < 0) { perror("telem: socket"); return -1; }

    memset(&dest_addr, 0, sizeof(dest_addr));
    dest_addr.sin_family = AF_INET;
    dest_addr.sin_port   = htons(TELEM_PORT);
    if (inet_pton(AF_INET, dest_ip, &dest_addr.sin_addr) != 1) {
        fprintf(stderr, "telem: invalid IP %s\n", dest_ip);
        close(sock); sock = -1; return -1;
    }

    burst_idx  = 0;
    seq        = 0;
    last_flags = 0;
    printf("telemetry → %s:%d  burst=%d\n", dest_ip, TELEM_PORT, TELEM_BURST);
    return 0;
}

void telem_push(float ia, float ib, float flux_a, float flux_b,
                float speed, uint8_t flags)
{
    if (sock < 0) return;

    last_flags              = flags;
    burst[burst_idx].ia     = ia;
    burst[burst_idx].ib     = ib;
    burst[burst_idx].flux_a = flux_a;
    burst[burst_idx].flux_b = flux_b;
    burst[burst_idx].speed  = speed;
    burst_idx++;

    if (burst_idx < TELEM_BURST) return;   /* accumulate */

    /* ── build frame ─────────────────────────────────────────────────────── */
    static uint8_t frame[MAX_FRAME];
    size_t pos = 0;

    /* SYNC */
    frame[pos++] = TELEM_SYNC_0;
    frame[pos++] = TELEM_SYNC_1;
    frame[pos++] = TELEM_SYNC_2;
    frame[pos++] = TELEM_SYNC_3;

    /* SEQ little-endian */
    frame[pos++] = (uint8_t)(seq      );
    frame[pos++] = (uint8_t)(seq >>  8);
    frame[pos++] = (uint8_t)(seq >> 16);
    frame[pos++] = (uint8_t)(seq >> 24);
    seq++;

    frame[pos++] = last_flags;
    frame[pos++] = (uint8_t)TELEM_BURST;

    /* samples — 5 × float32 LE each */
    for (int i = 0; i < TELEM_BURST; i++) {
        memcpy(frame + pos, &burst[i].ia,     sizeof(float)); pos += 4;
        memcpy(frame + pos, &burst[i].ib,     sizeof(float)); pos += 4;
        memcpy(frame + pos, &burst[i].flux_a, sizeof(float)); pos += 4;
        memcpy(frame + pos, &burst[i].flux_b, sizeof(float)); pos += 4;
        memcpy(frame + pos, &burst[i].speed,  sizeof(float)); pos += 4;
    }

    /* CRC16 over header + samples */
    uint16_t crc = crc16(frame, pos);
    frame[pos++] = (uint8_t)(crc     );
    frame[pos++] = (uint8_t)(crc >> 8);

    sendto(sock, frame, pos, 0,
           (struct sockaddr *)&dest_addr, sizeof(dest_addr));

    burst_idx = 0;
}

void telem_deinit(void)
{
    if (sock >= 0) { close(sock); sock = -1; }
}
