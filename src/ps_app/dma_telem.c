#include "dma_telem.h"

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdatomic.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>
#include <time.h>
#include <errno.h>

/* ── Xilinx AXI DMA register offsets (S2MM path only) ───────────────────── */
#define DMA_BASE_ADDR  0x40400000U
#define DMA_MAP_SIZE   0x10000U

/* Reserved DDR telemetry buffers: system-user.dtsi reserves this no-map window. */
#define DMA_BUF_PHYS_BASE 0x0F000000U
#define DMA_BUF_PHYS_SIZE 0x01000000U

#define S2MM_DMACR     0x30U
#define S2MM_DMASR     0x34U
#define S2MM_DA        0x48U
#define S2MM_DA_MSB    0x4CU
#define S2MM_LENGTH    0x58U

#define DMACR_RUN      (1u << 0)
#define DMACR_RESET    (1u << 2)

#define DMASR_HALTED   (1u << 0)
#define DMASR_INT_ERR  (1u << 4)   /* premature TLAST; RTL no longer asserts TLAST
                                    * on the telemetry stream, so this should not
                                    * fire anymore (kept as a guard). */
#define DMASR_IOC_IRQ  (1u << 12)
#define DMASR_ERR_IRQ  (1u << 14)

/* ── Internal state ──────────────────────────────────────────────────────── */
static int             mem_fd    = -1;
static volatile uint32_t *dma_regs = NULL;

/* Two physical buffers for double-buffering */
static void     *buf_virt[DMA_N_BUFS] = { NULL, NULL };
static uint32_t  buf_phys[DMA_N_BUFS] = { 0, 0 };
static void     *buf_map_virt = NULL;
static size_t    buf_map_size = 0;
static int       active_buf = 0;   /* which buffer the DMA is currently filling */

/* Set by dma_telem_resync() from any thread; consumed only by the thread
 * running dma_telem_next(), which owns all DMA register access. */
static atomic_int resync_pending = 0;

/* ── Register helpers ────────────────────────────────────────────────────── */
static inline void dma_wr(uint32_t off, uint32_t v) { dma_regs[off/4] = v; }
static inline uint32_t dma_rd(uint32_t off)         { return dma_regs[off/4]; }

static uint32_t be32(const uint8_t *p)
{
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) |
           ((uint32_t)p[2] << 8)  |  (uint32_t)p[3];
}

static int reserved_ddr_present(void)
{
    const char *path = "/proc/device-tree/reserved-memory/buffer@0f000000/reg";
    uint8_t reg[8];
    int fd = open(path, O_RDONLY);
    if (fd < 0) {
        fprintf(stderr, "dma_telem: reserved-memory node missing (%s)\n", path);
        return 0;
    }
    ssize_t n = read(fd, reg, sizeof(reg));
    close(fd);
    if (n != (ssize_t)sizeof(reg)) {
        fprintf(stderr, "dma_telem: reserved-memory reg has unexpected size\n");
        return 0;
    }
    uint32_t base = be32(reg);
    uint32_t size = be32(reg + 4);
    if (base != DMA_BUF_PHYS_BASE || size < DMA_BUF_PHYS_SIZE) {
        fprintf(stderr, "dma_telem: reserved-memory mismatch base=0x%08x size=0x%08x\n",
                base, size);
        return 0;
    }
    return 1;
}

/* ── Arm one S2MM transfer on the given buffer index ────────────────────── */
static void arm_transfer(int idx)
{
    /* Clear IOC/ERR flags, set destination, then write LENGTH to start */
    dma_wr(S2MM_DMASR, DMASR_IOC_IRQ | DMASR_ERR_IRQ);
    dma_wr(S2MM_DA,     buf_phys[idx]);
    dma_wr(S2MM_DA_MSB, 0);
    dma_wr(S2MM_LENGTH, DMA_BURST_BYTES);  /* this arms and starts */
}

/* Abort whatever transfer is in flight and start a clean one on active_buf. */
static void reset_and_rearm(void)
{
    dma_wr(S2MM_DMACR, DMACR_RESET);
    usleep(1000);
    dma_wr(S2MM_DMACR, DMACR_RUN);
    arm_transfer(active_buf);
}

/* ── Decode a 32-byte frame into dma_sample_t ───────────────────────────── */
static void decode_frame(const uint8_t *f, dma_sample_t *s)
{
    uint64_t w[4];
    memcpy(w, f, 32);

    /* Five 42-bit fields packed LSB-first at bit offsets 0, 42, 84, 126, 168 */
    float *dst[5] = { &s->ialpha, &s->ibeta,
                      &s->flux_alpha, &s->flux_beta, &s->speed };

    for (int k = 0; k < 5; k++) {
        int     blo   = k * 42;
        int     wlo   = blo / 64;
        int     shlo  = blo % 64;
        int     bhi   = blo + 41;
        int     whi   = bhi / 64;
        uint64_t val;

        if (wlo == whi) {
            val = (w[wlo] >> shlo) & 0x3FFFFFFFFFFull;
        } else {
            int bits_lo = 64 - shlo;
            int sh_hi   = bhi % 64;
            val = (w[wlo] >> shlo)
                | ((w[whi] & ((1ULL << (sh_hi + 1)) - 1)) << bits_lo);
        }

        /* Sign-extend 42-bit → int64 */
        int64_t sv = (val & (1ULL << 41))
                   ? (int64_t)(val | ~0x3FFFFFFFFFFull)
                   : (int64_t)val;

        *dst[k] = (float)sv * DMA_SCALE;
    }

    s->t_cycles = (uint32_t)((w[3] >> 18) & 0xFFFFFFFFu);
    s->epoch = (uint16_t)((w[3] >> 50) & 0x3FFFu);
}

/* ── Public API ──────────────────────────────────────────────────────────── */

int dma_telem_init(void)
{
    mem_fd = open("/dev/mem", O_RDWR | O_SYNC);
    if (mem_fd < 0) { perror("dma_telem: /dev/mem"); return -1; }

    if (!reserved_ddr_present()) {
        close(mem_fd);
        mem_fd = -1;
        return -1;
    }

    dma_regs = (volatile uint32_t *)mmap(NULL, DMA_MAP_SIZE,
                                         PROT_READ | PROT_WRITE,
                                         MAP_SHARED, mem_fd, DMA_BASE_ADDR);
    if (dma_regs == MAP_FAILED) {
        perror("dma_telem: mmap regs"); dma_regs = NULL; goto fail;
    }

    long pgsz = getpagesize();
    size_t bsz = ((DMA_BURST_BYTES + pgsz - 1) / pgsz) * pgsz;
    buf_map_size = bsz * DMA_N_BUFS;
    if (buf_map_size > DMA_BUF_PHYS_SIZE) {
        fprintf(stderr, "dma_telem: reserved DDR window too small\n");
        goto fail;
    }

    buf_map_virt = mmap(NULL, buf_map_size, PROT_READ | PROT_WRITE,
                        MAP_SHARED, mem_fd, DMA_BUF_PHYS_BASE);
    if (buf_map_virt == MAP_FAILED) {
        perror("dma_telem: mmap reserved DDR");
        buf_map_virt = NULL;
        goto fail;
    }
    memset(buf_map_virt, 0, buf_map_size);

    for (int i = 0; i < DMA_N_BUFS; i++) {
        buf_virt[i] = (uint8_t *)buf_map_virt + (size_t)i * bsz;
        buf_phys[i] = DMA_BUF_PHYS_BASE + (uint32_t)((size_t)i * bsz);
    }

    /* Reset S2MM channel then run */
    dma_wr(S2MM_DMACR, DMACR_RESET);
    for (int i = 0; i < 1000 && (dma_rd(S2MM_DMACR) & DMACR_RESET); i++)
        usleep(100);
    dma_wr(S2MM_DMACR, DMACR_RUN);

    if (dma_rd(S2MM_DMASR) & DMASR_HALTED) {
        fprintf(stderr, "dma_telem: S2MM halted (DMASR=0x%08x)\n",
                dma_rd(S2MM_DMASR));
        goto fail;
    }

    /* Arm first transfer on buffer 0 */
    active_buf = 0;
    arm_transfer(active_buf);

    printf("dma_telem: OK reserved DDR 0x%08x..0x%08x  buf[0]=0x%08x  buf[1]=0x%08x  burst=%d frames\n",
           DMA_BUF_PHYS_BASE, DMA_BUF_PHYS_BASE + (uint32_t)buf_map_size - 1u,
           buf_phys[0], buf_phys[1], DMA_BURST_FRAMES);
    return 0;

fail:
    dma_telem_deinit();
    return -1;
}

void dma_telem_deinit(void)
{
    if (dma_regs) {
        dma_wr(S2MM_DMACR, 0);   /* stop */
        munmap((void *)dma_regs, DMA_MAP_SIZE);
        dma_regs = NULL;
    }
    if (buf_map_virt) {
        munmap(buf_map_virt, buf_map_size);
        buf_map_virt = NULL;
        buf_map_size = 0;
    }
    for (int i = 0; i < DMA_N_BUFS; i++) {
        buf_virt[i] = NULL;
        buf_phys[i] = 0;
    }
    if (mem_fd >= 0) { close(mem_fd); mem_fd = -1; }
}

int dma_telem_next(dma_sample_t *out, int timeout_ms)
{
    if (!dma_regs || !buf_map_virt || !buf_virt[0]) return -1;

    /* ── Wait for current transfer to complete ────────────────────────────── */
    struct timespec t0, tn;
    clock_gettime(CLOCK_MONOTONIC, &t0);

    for (;;) {
        if (atomic_exchange(&resync_pending, 0)) {
            /* Caller is about to (or just did) pulse solver_reset, which holds
             * telem_clear_axi and silences the AXI4-Stream for ~2 ms — longer
             * than one burst. Abandon whatever partial burst is in flight now,
             * before that silence starts, so we never splice its tail onto the
             * next run's head. Costs at most one burst (~1.28 ms) of samples. */
            reset_and_rearm();
            return 0;
        }

        uint32_t sr = dma_rd(S2MM_DMASR);

        if (sr & DMASR_ERR_IRQ) {
            fprintf(stderr, "dma_telem: error DMASR=0x%08x\n", sr);
            reset_and_rearm();
            /* DMAIntErr (premature TLAST) should no longer occur: the RTL ties
             * the telemetry stream's TLAST low and lets S2MM complete purely by
             * the programmed length. If this still fires, treat it as a skipped
             * burst (return 0) rather than -1, so the caller does not count it
             * toward the GPIO fallback threshold. */
            return (sr & DMASR_INT_ERR) ? 0 : -1;
        }

        if (sr & DMASR_IOC_IRQ) break;

        clock_gettime(CLOCK_MONOTONIC, &tn);
        long ms = (tn.tv_sec - t0.tv_sec) * 1000L
                + (tn.tv_nsec - t0.tv_nsec) / 1000000L;
        if (ms > timeout_ms) {
            fprintf(stderr, "dma_telem: timeout %ld ms (DMASR=0x%08x)\n",
                    ms, dma_rd(S2MM_DMASR));
            return -1;
        }

        /* Busy-poll: simple-mode S2MM stops between transfers, so the window
         * from IOC to re-arm is dead time where samples are dropped. At 100 kHz
         * a burst is only ~1.28 ms, so the old 200 µs sleep left a ~6 % gap.
         * Spinning on DMASR cuts the re-arm latency to a few µs (<1 sample).
         * This thread is dedicated to telemetry and the Zynq has a spare core. */
    }

    /* Re-check: resync_pending may have been set in the tiny window between
     * the DMASR read that saw IOC_IRQ above and this point. Without this,
     * a burst that legitimately finished a few instructions before the
     * caller's resync request would still get decoded and returned as if
     * clean, even though solver_reset is about to (or already did) start
     * silencing the stream right after it. */
    if (atomic_exchange(&resync_pending, 0)) {
        reset_and_rearm();
        return 0;
    }

    /*
     * ── Double-buffer swap ─────────────────────────────────────────────────
     * Re-arm the DMA on the OTHER buffer FIRST so it starts immediately,
     * then decode the buffer that just finished. This minimises the gap
     * (a few µs for the register writes) during which tready=0.
     */
    int done_buf = active_buf;
    active_buf   = 1 - active_buf;
    arm_transfer(active_buf);          /* kick next transfer NOW */

    /* Buffer lives in reserved DDR mapped through /dev/mem O_SYNC. */
    uint8_t *raw = (uint8_t *)buf_virt[done_buf];

    /* Decode the completed buffer */
    for (int i = 0; i < DMA_BURST_FRAMES; i++)
        decode_frame(raw + i * DMA_FRAME_BYTES, &out[i]);

    /* Diagnostic: prove no burst splices two runs together. `epoch`
     * increments and `t_cycles` resets to 0 every time pwm_ctrl.enable
     * rises (PWM_Capture process, HIL_AXI_Top.vhd), so a run boundary
     * landing inside one decoded burst -- the exact corruption
     * dma_telem_resync() exists to prevent -- shows up as an epoch change
     * or a t_cycles drop between consecutive frames of the same buffer. */
    for (int i = 1; i < DMA_BURST_FRAMES; i++) {
        if (out[i].epoch != out[i - 1].epoch ||
            out[i].t_cycles < out[i - 1].t_cycles) {
            fprintf(stderr,
                "dma_telem: SPLICED BURST at frame %d/%d: epoch %u->%u "
                "t_cycles %u->%u (samples from two different runs mixed "
                "in one buffer)\n",
                i, DMA_BURST_FRAMES,
                out[i - 1].epoch, out[i].epoch,
                out[i - 1].t_cycles, out[i].t_cycles);
        }
    }

    return DMA_BURST_FRAMES;
}

void dma_telem_resync(void)
{
    atomic_store(&resync_pending, 1);
}
