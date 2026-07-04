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

#define UIO_LABEL       "vf_irq"
#define UIO_CLASS_DIR   "/sys/class/uio"
#define UIO_DEV_FMT     "/dev/%s"

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
        if (strcmp(label, UIO_LABEL) == 0) {
            snprintf(out_name, out_len, "%s", ent->d_name);
            closedir(d);
            return 0;
        }
    }
    closedir(d);
    fprintf(stderr, "vf_irq: nenhum /sys/class/uio/uioN com label \"%s\"\n", UIO_LABEL);
    return -1;
}

static void *uio_irq_thread(void *arg)
{
    (void)arg;
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
