#include "vf_irq.h"
#include "vf_ctrl.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <dirent.h>
#include <pthread.h>
#include <sched.h>
#include <time.h>

#define UIO_LABEL_PRIMARY   "vf-irq"
#define UIO_LABEL_LEGACY    "vf_irq"
#define UIO_CLASS_DIR   "/sys/class/uio"
#define UIO_DEV_FMT     "/dev/%s"

/* Cap on how many missed carrier ticks we replay in one go. A huge gap (e.g.
 * after being descheduled for a long time) is not meaningful to catch up
 * tick-for-tick; clamp instead of stalling the IRQ thread in a replay burst. */
#define VF_IRQ_MAX_CATCHUP  10

/* SCHED_FIFO priority for the tick thread. Above any SCHED_OTHER work in this
 * process (notably the busy-polling telemetry thread) but comfortably below
 * the kernel's threaded-IRQ handlers (irq/N-vf-irq runs at 50). */
#define VF_IRQ_RT_PRIO      40

/* A tick later than this (ms) means the thread was starved — worth reporting. */
#define VF_IRQ_LATE_MS      2.0
#define VF_IRQ_LATE_LOG_MAX 40

static int           uio_fd = -1;
static pthread_t     uio_tid;
static volatile int  uio_active = 0;

/* Procura em /sys/class/uio/uioN/name o dispositivo cujo conteudo bate com
 * UIO_LABEL, e devolve o nome do node em /dev (ex: "uio0"). Nao assume
 * indice fixo — o numero de uioN pode mudar entre boots conforme a ordem
 * de probe dos drivers. */
static int find_uio_device(char *out_name, size_t out_len)
{
    DIR *d = opendir(UIO_CLASS_DIR);
    if (!d) {
        fprintf(stderr, "vf_irq: opendir %s: %s\n", UIO_CLASS_DIR, strerror(errno));
        return -1;
    }
    struct dirent *ent;
    while ((ent = readdir(d)) != NULL) {
        if (strncmp(ent->d_name, "uio", 3) != 0) continue;
        char name_path[512];
        snprintf(name_path, sizeof(name_path), "%s/%s/name", UIO_CLASS_DIR, ent->d_name);
        FILE *f = fopen(name_path, "r");
        if (!f) continue;
        char label[128] = {0};
        if (fgets(label, sizeof(label), f) != NULL) {
            label[strcspn(label, "\n")] = '\0';
        }
        fclose(f);
        if (strcmp(label, UIO_LABEL_PRIMARY) == 0 || strcmp(label, UIO_LABEL_LEGACY) == 0) {
            snprintf(out_name, out_len, "%s", ent->d_name);
            closedir(d);
            return 0;
        }
    }
    closedir(d);
    fprintf(stderr, "vf_irq: nenhum /sys/class/uio/uioN com label \"%s\" ou \"%s\"\n", UIO_LABEL_PRIMARY, UIO_LABEL_LEGACY);
    return -1;
}

static void *uio_irq_thread(void *arg)
{
    (void)arg;
    uint32_t last_count = 0;
    int first = 1;
    struct timespec last_tick = {0, 0};
    int late_logged = 0;

    /* This thread carries the drive's hard real-time deadline: every carrier
     * period it must refresh va/vb/vc before the modulator latches them at
     * the next valley. The Zynq-7010 has only 2 cores and the telemetry
     * thread deliberately busy-polls the DMA status register (see
     * dma_telem.c), so under SCHED_OTHER the scheduler is free to leave this
     * thread runnable-but-not-running for a full timeslice — tens of ms.
     * The FPGA does not stall meanwhile: it keeps switching on the stale
     * reference, so the missed window becomes a real volt-second error and
     * the motor answers with a large current/torque transient. SCHED_FIFO
     * lets this thread preempt the spinner immediately. */
    {
        struct sched_param sp;
        memset(&sp, 0, sizeof(sp));
        sp.sched_priority = VF_IRQ_RT_PRIO;
        if (pthread_setschedparam(pthread_self(), SCHED_FIFO, &sp) != 0)
            fprintf(stderr, "vf_irq: SCHED_FIFO prio %d indisponivel (%s) — "
                            "seguindo em SCHED_OTHER; jitter de tick possivel\n",
                    VF_IRQ_RT_PRIO, strerror(errno));
    }

    while (uio_active) {
        uint32_t count;
        ssize_t n = read(uio_fd, &count, sizeof(count));
        if (n != (ssize_t)sizeof(count)) {
            if (!uio_active) break;  /* fd fechado por vf_irq_stop() */
            fprintf(stderr, "vf_irq: read /dev/uio inesperado (n=%zd): %s\n",
                    n, strerror(errno));
            break;
        }
        if (!uio_active) break;

        /* uio_pdrv_genirq's read() returns the interrupt counter as of this
         * wakeup, not a delta. If this thread gets descheduled for more than
         * one carrier period (~1ms), the kernel keeps counting ticks that we
         * never consumed. Calling vf_tick() only once here — regardless of
         * how many ticks actually elapsed — lets the commanded electrical
         * angle (theta) fall behind the FPGA's own carrier, which keeps
         * running with the stale va/vb/vc reference for the whole missed
         * gap. When the angle "catches up" on the next tick it jumps ahead
         * relative to where the solver's flux state actually is, injecting
         * a real phase-angle disturbance that the (open-loop, uncorrected)
         * V/F drive then has to ride out — exactly the large-but-smooth
         * current/torque transients seen in the telemetry. Replaying
         * vf_tick() once per missed period keeps theta consistent with the
         * hardware's real elapsed time instead of an assumed fixed step. */
        uint32_t missed = first ? 1 : (count - last_count);
        last_count = count;
        if (missed == 0) missed = 1;           /* spurious wakeup guard */
        if (missed > VF_IRQ_MAX_CATCHUP)
            missed = VF_IRQ_MAX_CATCHUP;

        /* Diagnostic: measure how long this thread was actually away. A
         * healthy tick is 1 ms; anything materially longer means the thread
         * was starved and va/vb/vc sat frozen in the FPGA for that whole
         * window (the volt-second error that shows up as a current/torque
         * transient). Logged rate-limited so a bad run cannot flood. */
        struct timespec now;
        clock_gettime(CLOCK_MONOTONIC, &now);
        if (!first) {
            double dt_ms = (now.tv_sec - last_tick.tv_sec) * 1000.0
                         + (now.tv_nsec - last_tick.tv_nsec) / 1.0e6;
            if (dt_ms > VF_IRQ_LATE_MS && late_logged < VF_IRQ_LATE_LOG_MAX) {
                late_logged++;
                fprintf(stderr,
                    "vf_irq: LATE tick dt=%.2f ms (esperado ~1.00, missed=%u)%s\n",
                    dt_ms, missed,
                    late_logged == VF_IRQ_LATE_LOG_MAX ? " [ultimo aviso]" : "");
            }
        }
        last_tick = now;
        first = 0;

        for (uint32_t i = 0; i < missed; i++)
            vf_tick();

        /* Contrato UIO: escrever de volta reabilita a IRQ no kernel */
        uint32_t reenable = 1;
        if (write(uio_fd, &reenable, sizeof(reenable)) != (ssize_t)sizeof(reenable)) {
            fprintf(stderr, "vf_irq: write reenable falhou: %s\n", strerror(errno));
            break;
        }
    }
    return NULL;
}

int vf_irq_start(void)
{
    char dev_name[300];
    if (find_uio_device(dev_name, sizeof(dev_name)) != 0) return -1;

    char dev_path[320];
    snprintf(dev_path, sizeof(dev_path), UIO_DEV_FMT, dev_name);
    uio_fd = open(dev_path, O_RDWR);
    if (uio_fd < 0) {
        fprintf(stderr, "vf_irq: open %s: %s\n", dev_path, strerror(errno));
        return -1;
    }

    vf_tick();  /* "queimada de partida", mesma logica que setup_vf_timer() tinha */

    /* uio_pdrv_genirq pode nascer com a IRQ ja mascarada e um evento pendente
     * (ex: um glitch no boot, antes deste processo abrir o fd) -- o reader
     * so' desbloqueia em read() quando a contagem passa do valor que tinha
     * no open(), entao sem este write inicial a thread abaixo fica presa
     * pra sempre no primeiro read(), esperando uma contagem que nunca vem
     * porque ninguem jamais desmascarou a IRQ no GIC. Confirmado no board:
     * ISENABLER1 bit29=0 (IRQ 61 mascarada) com ICPENDR1 bit29=1 (pendente)
     * enquanto a portadora ja pulsava continuamente no hardware. */
    {
        uint32_t reenable = 1;
        if (write(uio_fd, &reenable, sizeof(reenable)) != (ssize_t)sizeof(reenable)) {
            fprintf(stderr, "vf_irq: write inicial de reenable falhou: %s\n", strerror(errno));
        }
    }

    uio_active = 1;
    if (pthread_create(&uio_tid, NULL, uio_irq_thread, NULL) != 0) {
        perror("vf_irq: pthread_create");
        uio_active = 0;
        close(uio_fd);
        uio_fd = -1;
        return -1;
    }
    return 0;
}

void vf_irq_stop(void)
{
    if (!uio_active) return;
    uio_active = 0;
    if (uio_fd >= 0) close(uio_fd);  /* desbloqueia o read() pendente */
    pthread_join(uio_tid, NULL);
    uio_fd = -1;
}
