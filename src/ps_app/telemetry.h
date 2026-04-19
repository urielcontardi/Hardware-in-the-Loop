#ifndef TELEMETRY_H
#define TELEMETRY_H

#include <stdint.h>

/*
 * Telemetry UDP push — binary burst protocol
 *
 * Frame layout (little-endian):
 *  [0..3]   SYNC  0x48 0x49 0x4C 0x5A  ("HILZ")
 *  [4..7]   SEQ   uint32 LE  (increments per burst)
 *  [8]      FLAGS uint8  (bit0=enable, bit1=fault)
 *  [9]      N     uint8  (samples in this burst)
 *  [10 .. 10+N*20-1]  samples: ia ib flux_a flux_b speed (float32 LE each)
 *  [last-1..last]     CRC16/CCITT-FALSE LE
 *
 * Total for burst of 32: 4+4+1+1+(32×20)+2 = 652 bytes
 */

#define TELEM_SYNC_0  0x48u
#define TELEM_SYNC_1  0x49u
#define TELEM_SYNC_2  0x4Cu
#define TELEM_SYNC_3  0x5Au

#define TELEM_PORT    5006
#define TELEM_BURST   32     /* samples per UDP packet */

typedef struct {
    float ia;
    float ib;
    float flux_a;
    float flux_b;
    float speed;
} telem_sample_t;

/*
 * telem_init  — open UDP socket, set destination IP
 *               call once, or again to retarget
 * telem_push  — accumulate one sample; sends burst when TELEM_BURST reached
 * telem_deinit— close socket
 */
int  telem_init  (const char *dest_ip);
void telem_push  (float ia, float ib, float flux_a, float flux_b,
                  float speed, uint8_t flags);
void telem_deinit(void);

#endif /* TELEMETRY_H */
