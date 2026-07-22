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
 *   bits [241:210]— run-local timestamp (100 MHz)
 *   bits [255:242]— run epoch (low 14 bits)
 *
 * One frame = 32 bytes.  At decim=750 → ~10 kHz; decim=77 → ~100 kHz.
 *
 * Physical value = raw_int42 / 2^28  (same as GPIO path / 2^18 on top-32).
 */

#define DMA_FRAME_BYTES   32          /* 256-bit AXI Stream beat             */
#define DMA_BURST_FRAMES  128         /* frames per DMA transfer (~1.28 ms at 100k) */
#define DMA_BURST_BYTES   (DMA_BURST_FRAMES * DMA_FRAME_BYTES)
#define DMA_N_BUFS        2           /* double-buffer: DMA always active     */

/* Q14.28 scale: physical = raw / 2^28 */
#define DMA_SCALE         (1.0f / (float)(1u << 28))

typedef struct {
    uint32_t t_cycles;
    uint16_t epoch;
    float ialpha;
    float ibeta;
    float flux_alpha;
    float flux_beta;
    float speed;
} dma_sample_t;

/*
 * dma_telem_init — open /dev/mem, mmap DMA regs and split the reserved DDR
 *                  telemetry window into two DMA buffers before arming S2MM.
 * Returns 0 on success, -1 on error.
 */
int  dma_telem_init(void);

/*
 * dma_telem_deinit — stop DMA, unmap and release everything.
 */
void dma_telem_deinit(void);

/*
 * dma_telem_next — wait for the current DMA transfer to complete, decode
 *                  the filled buffer into `out`, then immediately re-arm
 *                  DMA on the other buffer (double-buffer swap).
 *
 * `out` must point to at least DMA_BURST_FRAMES dma_sample_t entries.
 *
 * Returns DMA_BURST_FRAMES on success, -1 on error/timeout.
 * timeout_ms is per transfer; at 100 kHz each transfer takes ~1.28 ms.
 */
int dma_telem_next(dma_sample_t *out, int timeout_ms);

/*
 * dma_telem_resync — request that the in-flight S2MM transfer be abandoned
 *                    and re-armed clean on its next poll.
 *
 * Call this right before pulsing the solver_reset GPIO bit (which holds the
 * RTL's telem_clear_axi and silences the AXI4-Stream for ~2 ms — longer
 * than one DMA burst). Without this, whatever partial burst was in flight
 * when the stream goes silent sits parked mid-transfer; once the stream
 * resumes, the remaining bytes are filled from the NEW run and the buffer
 * decodes as one contiguous burst splicing old-run tail with new-run head,
 * showing up as a large spurious discontinuity. Discarding the partial
 * burst here costs at most one burst (~1.28 ms) of samples but keeps every
 * decoded burst internally consistent.
 *
 * Safe to call even if DMA telemetry was never initialized or is not the
 * active telemetry source (no-op in that case). Lock-free: only sets a
 * flag polled by the thread that owns the DMA registers (dma_telem_next),
 * so it never touches hardware registers from the caller's thread.
 */
void dma_telem_resync(void);

#endif /* DMA_TELEM_H */
