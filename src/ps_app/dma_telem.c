#include "dma_telem.h"

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>
#include <time.h>
#include <errno.h>

/* ── Xilinx AXI DMA register offsets (S2MM path only) ───────────────────── */
#define DMA_BASE_ADDR  0x40400000U
#define DMA_MAP_SIZE   0x10000U

#define S2MM_DMACR     0x30U
#define S2MM_DMASR     0x34U
#define S2MM_DA        0x48U
#define S2MM_DA_MSB    0x4CU
#define S2MM_LENGTH    0x58U

#define DMACR_RUN      (1u << 0)
#define DMACR_RESET    (1u << 2)

#define DMASR_HALTED   (1u << 0)
#define DMASR_IOC_IRQ  (1u << 12)
#define DMASR_ERR_IRQ  (1u << 14)

/* ── Internal state ──────────────────────────────────────────────────────── */
static int             mem_fd    = -1;
static volatile uint32_t *dma_regs = NULL;

/* Two physical buffers for double-buffering */
static void     *buf_virt[DMA_N_BUFS] = { NULL, NULL };
static uint32_t  buf_phys[DMA_N_BUFS] = { 0, 0 };
static int       active_buf = 0;   /* which buffer the DMA is currently filling */

/* ── Register helpers ────────────────────────────────────────────────────── */
static inline void dma_wr(uint32_t off, uint32_t v) { dma_regs[off/4] = v; }
static inline uint32_t dma_rd(uint32_t off)         { return dma_regs[off/4]; }

/* ── Physical address lookup via /proc/self/pagemap ─────────────────────── */
static uint32_t virt_to_phys(const void *va)
{
    int fd = open("/proc/self/pagemap", O_RDONLY);
    if (fd < 0) { perror("pagemap open"); return 0; }

    long   pgsz  = getpagesize();
    size_t page  = (uintptr_t)va / pgsz;
    uint64_t ent = 0;
    if (pread(fd, &ent, 8, (off_t)(page * 8)) != 8) {
        perror("pagemap pread"); close(fd); return 0;
    }
    close(fd);
    if (!(ent & (1ULL << 63))) {
        fprintf(stderr, "dma_telem: page not present\n"); return 0;
    }
    uint64_t pfn = ent & ((1ULL << 55) - 1);
    return (uint32_t)(pfn * pgsz + (uintptr_t)va % pgsz);
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
}

/* ── Public API ──────────────────────────────────────────────────────────── */

int dma_telem_init(void)
{
    mem_fd = open("/dev/mem", O_RDWR | O_SYNC);
    if (mem_fd < 0) { perror("dma_telem: /dev/mem"); return -1; }

    dma_regs = (volatile uint32_t *)mmap(NULL, DMA_MAP_SIZE,
                                         PROT_READ | PROT_WRITE,
                                         MAP_SHARED, mem_fd, DMA_BASE_ADDR);
    if (dma_regs == MAP_FAILED) {
        perror("dma_telem: mmap regs"); dma_regs = NULL; goto fail;
    }

    long pgsz = getpagesize();
    size_t bsz = ((DMA_BURST_BYTES + pgsz - 1) / pgsz) * pgsz;

    for (int i = 0; i < DMA_N_BUFS; i++) {
        if (posix_memalign(&buf_virt[i], pgsz, bsz) != 0) {
            perror("dma_telem: posix_memalign"); goto fail;
        }
        memset(buf_virt[i], 0, bsz);
        if (mlock(buf_virt[i], bsz) != 0) {
            perror("dma_telem: mlock"); goto fail;
        }
        buf_phys[i] = virt_to_phys(buf_virt[i]);
        if (buf_phys[i] == 0) goto fail;
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

    printf("dma_telem: OK  buf[0]=0x%08x  buf[1]=0x%08x  burst=%d frames\n",
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
    long pgsz = getpagesize();
    size_t bsz = ((DMA_BURST_BYTES + pgsz - 1) / pgsz) * pgsz;
    for (int i = 0; i < DMA_N_BUFS; i++) {
        if (buf_virt[i]) {
            munlock(buf_virt[i], bsz);
            free(buf_virt[i]);
            buf_virt[i] = NULL;
        }
        buf_phys[i] = 0;
    }
    if (mem_fd >= 0) { close(mem_fd); mem_fd = -1; }
}

int dma_telem_next(dma_sample_t *out, int timeout_ms)
{
    if (!dma_regs || !buf_virt[0]) return -1;

    /* ── Wait for current transfer to complete ────────────────────────────── */
    struct timespec t0, tn;
    clock_gettime(CLOCK_MONOTONIC, &t0);

    for (;;) {
        uint32_t sr = dma_rd(S2MM_DMASR);

        if (sr & DMASR_ERR_IRQ) {
            fprintf(stderr, "dma_telem: error DMASR=0x%08x\n", sr);
            /* Reset and re-arm */
            dma_wr(S2MM_DMACR, DMACR_RESET);
            usleep(1000);
            dma_wr(S2MM_DMACR, DMACR_RUN);
            arm_transfer(active_buf);
            return -1;
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

        usleep(200);  /* ~0.2 ms poll interval — burst is ~13 ms */
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

    /*
     * ── WARNING: cache-coherency bug on this path ─────────────────────────
     * The AXI DMA writes through S_AXI_HP0 which is NOT coherent with the
     * Cortex-A9 L1 D-cache. The CPU caches DMA-buffer lines on first read;
     * on subsequent bursts DDR is fresh but reads hit stale cache lines, so
     * decoded samples mix old + new data. This shows up as high-frequency
     * "ripple" on fast signals (Ia, Ib, flux α/β) while speed looks smooth.
     *
     * Verified empirically: GPIO polling (uncached /dev/mem O_SYNC) gives
     * Ia ZC ≈ 138 Hz (≈2× fund.); this DMA path gives Ia ZC ≈ 2280 Hz.
     *
     * Userspace on standard PetaLinux has no way to invalidate D-cache:
     *   - __builtin___clear_cache() / cacheflush syscall only clean D-cache
     *     and invalidate I-cache (intended for self-modifying code).
     *   - L2 (PL310) operations are kernel-only.
     *   - No udmabuf / dma_heap / uio drivers in this image.
     *
     * Proper fix options:
     *   A) Re-route axi_dma_0/M_AXI_S2MM to processing_system7_0/S_AXI_ACP
     *      in the Vivado block design (Accelerator Coherency Port snoops L1
     *      and is fully coherent). Requires PCW_USE_S_AXI_ACP=1 +
     *      S_AXI_ACP_ACLK connection and re-implementing the project.
     *   B) Reserve uncached DDR via 'reserved-memory' node in the device
     *      tree, mmap that physical range via /dev/mem with O_SYNC.
     *   C) Build a kernel module that exposes a D-cache invalidate ioctl.
     *
     * Until one of A/B/C lands, src/ps_app/main.c forces use_dma = 0 and the
     * controller runs on GPIO polling, which is provably coherent.
     */
    uint8_t *raw = (uint8_t *)buf_virt[done_buf];

    /* Decode the completed buffer */
    for (int i = 0; i < DMA_BURST_FRAMES; i++)
        decode_frame(raw + i * DMA_FRAME_BYTES, &out[i]);

    return DMA_BURST_FRAMES;
}
