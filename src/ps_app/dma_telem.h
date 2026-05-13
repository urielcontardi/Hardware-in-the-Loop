#ifndef DMA_TELEM_H
#define DMA_TELEM_H

#include <stdint.h>

/*
 * DMA telemetry — reads solver outputs via the Xilinx AXI DMA S2MM channel.
 *
 * The FPGA's AXI4-Stream output packs 5 solver signals (42-bit Q14.28 each)
 * into 256-bit frames at the rate controlled by `decim` in pwm_ctrl:
 *
 *   bits [41:0]   — ialpha   (Q14.28 signed)
 *   bits [83:42]  — ibeta
 *   bits [125:84] — flux_alpha
 *   bits [167:126]— flux_beta
 *   bits [209:168]— speed_mech
 *   bits [255:210]— padding (zero)
 *
 * One frame = 32 bytes.  At decim=375 → ~10 kHz; decim=37 → ~100 kHz.
 *
 * Physical value = raw_int42 / 2^28  (same as GPIO path / 2^18 on top-32).
 */

#define DMA_FRAME_BYTES   32          /* 256-bit AXI Stream beat */
#define DMA_BURST_FRAMES  512         /* frames per DMA transfer  */
#define DMA_BURST_BYTES   (DMA_BURST_FRAMES * DMA_FRAME_BYTES)

/* Q14.28 scale: physical = raw / 2^28 */
#define DMA_SCALE         (1.0f / (float)(1u << 28))

typedef struct {
    float ialpha;
    float ibeta;
    float flux_alpha;
    float flux_beta;
    float speed;
} dma_sample_t;

/*
 * dma_telem_init — open /dev/mem, mmap DMA regs and allocate a DMA-coherent
 *                  buffer using the pagemap trick.
 * Returns 0 on success, -1 on error.
 */
int  dma_telem_init(void);

/*
 * dma_telem_deinit — stop DMA, unmap and release everything.
 */
void dma_telem_deinit(void);

/*
 * dma_telem_transfer — start a DMA transfer of DMA_BURST_FRAMES frames and
 *                      block until completion (or timeout_ms milliseconds).
 * On success fills `out[0..DMA_BURST_FRAMES-1]` and returns DMA_BURST_FRAMES.
 * Returns -1 on error or timeout.
 */
int dma_telem_transfer(dma_sample_t *out, int timeout_ms);

#endif /* DMA_TELEM_H */
