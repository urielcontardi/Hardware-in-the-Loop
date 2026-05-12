#include "dma_telem.h"

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/time.h>
#include <time.h>
#include <errno.h>

/* ── Xilinx AXI DMA register offsets (S2MM path) ────────────────────────── */
#define DMA_BASE_ADDR      0x40400000U
#define DMA_MAP_SIZE       0x10000U

/* S2MM register offsets */
#define S2MM_DMACR         0x30U   /* control  */
#define S2MM_DMASR         0x34U   /* status   */
#define S2MM_DA            0x48U   /* dest address (lower 32 bits) */
#define S2MM_DA_MSB        0x4CU   /* dest address upper (unused on 32-bit) */
#define S2MM_LENGTH        0x58U   /* transfer length in bytes (arms DMA) */

/* DMACR bits */
#define DMACR_RUN          (1u << 0)   /* 1 = run, 0 = stop */
#define DMACR_RESET        (1u << 2)   /* pulse to reset */
#define DMACR_IOC_IRQ_EN   (1u << 12)  /* interrupt on complete (not used) */

/* DMASR bits */
#define DMASR_HALTED       (1u << 0)
#define DMASR_IDLE         (1u << 1)
#define DMASR_IOC_IRQ      (1u << 12)  /* transfer complete */
#define DMASR_ERR_IRQ      (1u << 14)  /* error */

/* ── Internal state ──────────────────────────────────────────────────────── */
static int            mem_fd      = -1;
static volatile uint32_t *dma_regs = NULL;  /* mmap of DMA registers */
static void          *dma_buf_virt = NULL;   /* virtual address of DMA buffer */
static uint32_t       dma_buf_phys = 0;      /* physical address */

/* ── Helpers ─────────────────────────────────────────────────────────────── */

static inline void dma_write(uint32_t offset, uint32_t val)
{
    dma_regs[offset / 4] = val;
}

static inline uint32_t dma_read(uint32_t offset)
{
    return dma_regs[offset / 4];
}

/*
 * virt_to_phys — translate a virtual address of a mlock'd page to its
 * physical address using /proc/self/pagemap.
 *
 * Works on Zynq-7000 without SMMU because Linux identity-maps DDR and the
 * physical address returned by pagemap is the real bus address the DMA sees.
 */
static uint32_t virt_to_phys(const void *vaddr)
{
    int fd = open("/proc/self/pagemap", O_RDONLY);
    if (fd < 0) {
        perror("dma_telem: open pagemap");
        return 0;
    }

    uintptr_t page = (uintptr_t)vaddr / getpagesize();
    uint64_t entry = 0;
    if (pread(fd, &entry, sizeof(entry), (off_t)(page * sizeof(entry))) != sizeof(entry)) {
        perror("dma_telem: pread pagemap");
        close(fd);
        return 0;
    }
    close(fd);

    if (!(entry & (1ULL << 63))) {
        fprintf(stderr, "dma_telem: page not present in pagemap\n");
        return 0;
    }

    uint64_t pfn = entry & ((1ULL << 55) - 1);
    return (uint32_t)((pfn * getpagesize()) + ((uintptr_t)vaddr % getpagesize()));
}

/* ── Public API ──────────────────────────────────────────────────────────── */

int dma_telem_init(void)
{
    mem_fd = open("/dev/mem", O_RDWR | O_SYNC);
    if (mem_fd < 0) {
        perror("dma_telem: open /dev/mem");
        return -1;
    }

    /* Map DMA registers */
    dma_regs = (volatile uint32_t *)mmap(NULL, DMA_MAP_SIZE,
                                         PROT_READ | PROT_WRITE,
                                         MAP_SHARED, mem_fd,
                                         DMA_BASE_ADDR);
    if (dma_regs == MAP_FAILED) {
        perror("dma_telem: mmap DMA regs");
        dma_regs = NULL;
        close(mem_fd); mem_fd = -1;
        return -1;
    }

    /* Allocate a page-aligned, physically contiguous DMA buffer.
     * mlock forces the pages into RAM so pagemap gives a stable PFN. */
    long page_sz = getpagesize();
    size_t buf_sz = ((DMA_BURST_BYTES + page_sz - 1) / page_sz) * page_sz;

    if (posix_memalign(&dma_buf_virt, page_sz, buf_sz) != 0) {
        perror("dma_telem: posix_memalign");
        goto fail;
    }
    memset(dma_buf_virt, 0, buf_sz);

    if (mlock(dma_buf_virt, buf_sz) != 0) {
        perror("dma_telem: mlock");
        goto fail;
    }

    dma_buf_phys = virt_to_phys(dma_buf_virt);
    if (dma_buf_phys == 0) {
        fprintf(stderr, "dma_telem: could not determine physical address\n");
        goto fail;
    }

    /* Reset and start the S2MM channel */
    dma_write(S2MM_DMACR, DMACR_RESET);
    /* spin until reset clears */
    for (int i = 0; i < 1000; i++) {
        if (!(dma_read(S2MM_DMACR) & DMACR_RESET)) break;
        usleep(100);
    }
    dma_write(S2MM_DMACR, DMACR_RUN);

    uint32_t sr = dma_read(S2MM_DMASR);
    if (sr & DMASR_HALTED) {
        fprintf(stderr, "dma_telem: S2MM halted after init (DMASR=0x%08x)\n", sr);
        goto fail;
    }

    printf("dma_telem: init OK  buf_virt=%p  buf_phys=0x%08x  frames=%d\n",
           dma_buf_virt, dma_buf_phys, DMA_BURST_FRAMES);
    return 0;

fail:
    dma_telem_deinit();
    return -1;
}

void dma_telem_deinit(void)
{
    if (dma_regs) {
        /* Stop the S2MM channel gracefully */
        dma_write(S2MM_DMACR, 0);
        munmap((void *)dma_regs, DMA_MAP_SIZE);
        dma_regs = NULL;
    }
    if (dma_buf_virt) {
        munlock(dma_buf_virt, DMA_BURST_BYTES);
        free(dma_buf_virt);
        dma_buf_virt = NULL;
    }
    if (mem_fd >= 0) {
        close(mem_fd);
        mem_fd = -1;
    }
    dma_buf_phys = 0;
}

int dma_telem_transfer(dma_sample_t *out, int timeout_ms)
{
    if (!dma_regs || !dma_buf_virt) return -1;

    /* Clear IOC flag by writing 1 to it */
    dma_write(S2MM_DMASR, DMASR_IOC_IRQ | DMASR_ERR_IRQ);

    /* Write destination address then length (length arms the transfer) */
    dma_write(S2MM_DA,     dma_buf_phys);
    dma_write(S2MM_DA_MSB, 0);
    dma_write(S2MM_LENGTH, DMA_BURST_BYTES);

    /* Poll for completion */
    struct timespec t0, tnow;
    clock_gettime(CLOCK_MONOTONIC, &t0);

    for (;;) {
        uint32_t sr = dma_read(S2MM_DMASR);

        if (sr & DMASR_ERR_IRQ) {
            fprintf(stderr, "dma_telem: DMA error DMASR=0x%08x\n", sr);
            /* Reset and re-arm for next call */
            dma_write(S2MM_DMACR, DMACR_RESET);
            usleep(1000);
            dma_write(S2MM_DMACR, DMACR_RUN);
            return -1;
        }

        if (sr & DMASR_IOC_IRQ) break;   /* transfer complete */

        clock_gettime(CLOCK_MONOTONIC, &tnow);
        long elapsed_ms = (tnow.tv_sec  - t0.tv_sec)  * 1000L
                        + (tnow.tv_nsec - t0.tv_nsec) / 1000000L;
        if (elapsed_ms > timeout_ms) {
            fprintf(stderr, "dma_telem: timeout after %ld ms (DMASR=0x%08x)\n",
                    elapsed_ms, dma_read(S2MM_DMASR));
            return -1;
        }

        /* Short busy-wait — the transfer at 10 kHz takes ~51 ms */
        usleep(100);
    }

    /*
     * Decode 256-bit frames from the raw buffer.
     *
     * Layout per frame (little-endian, 32 bytes):
     *   uint64_t word0: ialpha   [41:0]  in bits [41:0]
     *   uint64_t word1: ibeta    in bits [41:0] of the next 64 bits
     *                   (shares word boundary: word0 bits[63:42] + word1 bits[19:0])
     *
     * Simpler: treat as 5 consecutive 42-bit fields packed into 256 bits.
     * Extract using bit-level access on the 32-byte block.
     */
    const uint8_t *raw = (const uint8_t *)dma_buf_virt;

    for (int i = 0; i < DMA_BURST_FRAMES; i++) {
        const uint8_t *f = raw + i * DMA_FRAME_BYTES;

        /* Read 256 bits as four uint64_t (little-endian) */
        uint64_t w[4];
        memcpy(w, f, 32);

        /* Extract five 42-bit signed fields.
         * The FPGA packs them LSB-first starting at bit 0:
         *   field k occupies bits [42k+41 : 42k]
         */
        int64_t raw42[5];
        /* 256-bit value as 256-bit big array:
         * field 0: bits [41:0]
         * field 1: bits [83:42]
         * field 2: bits [125:84]
         * field 3: bits [167:126]
         * field 4: bits [209:168]
         */

        /* Pack all 256 bits into a 32-byte array, then extract */
        for (int k = 0; k < 5; k++) {
            int  bit_lo = k * 42;
            int  bit_hi = bit_lo + 41;
            int  w_lo   = bit_lo / 64;
            int  sh_lo  = bit_lo % 64;
            int  w_hi   = bit_hi / 64;
            int  sh_hi  = bit_hi % 64;

            uint64_t val;
            if (w_lo == w_hi) {
                val = (w[w_lo] >> sh_lo) & 0x3FFFFFFFFFFull;
            } else {
                /* spans two uint64_t words */
                int bits_from_lo = 64 - sh_lo;
                val = (w[w_lo] >> sh_lo)
                    | ((w[w_hi] & ((1ULL << (sh_hi + 1)) - 1)) << bits_from_lo);
            }

            /* sign-extend 42-bit to int64 */
            if (val & (1ULL << 41))
                raw42[k] = (int64_t)(val | ~0x3FFFFFFFFFFull);
            else
                raw42[k] = (int64_t)val;
        }

        out[i].ialpha     = (float)raw42[0] * DMA_SCALE;
        out[i].ibeta      = (float)raw42[1] * DMA_SCALE;
        out[i].flux_alpha = (float)raw42[2] * DMA_SCALE;
        out[i].flux_beta  = (float)raw42[3] * DMA_SCALE;
        out[i].speed      = (float)raw42[4] * DMA_SCALE;
    }

    return DMA_BURST_FRAMES;
}
