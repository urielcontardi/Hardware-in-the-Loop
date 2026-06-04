#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

#define SUPERVISOR_PORT 5010
#define CMD_PORT_HEX    "138D"  /* 5005 */
#define CONTROLLER_PATH "/home/petalinux/hil_controller"
#define CONTROLLER_LOG  "/home/petalinux/hil_controller.log"

static time_t started_at;

static int read_first_pid(const char *name)
{
    char cmd[128];
    char buf[64];
    FILE *fp;
    int pid = 0;

    snprintf(cmd, sizeof(cmd), "pidof %s 2>/dev/null", name);
    fp = popen(cmd, "r");
    if (!fp)
        return 0;
    if (fgets(buf, sizeof(buf), fp))
        pid = atoi(buf);
    pclose(fp);
    return pid;
}

static char read_proc_state(int pid)
{
    char path[64];
    char line[256];
    FILE *fp;
    char state = '?';

    if (pid <= 0)
        return state;

    snprintf(path, sizeof(path), "/proc/%d/status", pid);
    fp = fopen(path, "r");
    if (!fp)
        return state;

    while (fgets(line, sizeof(line), fp)) {
        if (strncmp(line, "State:", 6) == 0) {
            char *p = strchr(line, '\t');
            if (p && p[1])
                state = p[1];
            break;
        }
    }
    fclose(fp);
    return state;
}

static uint32_t udp5005_rx_queue(void)
{
    FILE *fp = fopen("/proc/net/udp", "r");
    char line[512];
    uint32_t rxq = 0;

    if (!fp)
        return 0;

    while (fgets(line, sizeof(line), fp)) {
        char local[64];
        char txrx[64];

        if (sscanf(line, "%*d: %63s %*s %*s %63s", local, txrx) != 2)
            continue;
        if (!strstr(local, ":" CMD_PORT_HEX))
            continue;

        char *colon = strchr(txrx, ':');
        if (colon)
            rxq = (uint32_t)strtoul(colon + 1, NULL, 16);
        break;
    }

    fclose(fp);
    return rxq;
}

static void write_json_status(char *out, size_t outsz, const char *status)
{
    int pid = read_first_pid("hil_controller");
    char state = read_proc_state(pid);
    long uptime = (long)(time(NULL) - started_at);
    uint32_t rxq = udp5005_rx_queue();

    snprintf(out, outsz,
             "{\"status\":\"%s\","
             "\"supervisor\":\"ok\","
             "\"supervisor_port\":%d,"
             "\"uptime_s\":%ld,"
             "\"controller_pid\":%d,"
             "\"controller_running\":%d,"
             "\"controller_state\":\"%c\","
             "\"cmd5005_rx_queue_bytes\":%u}",
             status, SUPERVISOR_PORT, uptime, pid, pid > 0 ? 1 : 0,
             state, rxq);
}

static void stop_controller(void)
{
    int pid = read_first_pid("hil_controller");
    int waited;

    if (pid <= 0)
        return;

    kill(pid, SIGTERM);
    for (waited = 0; waited < 20; waited++) {
        usleep(100000);
        if (read_first_pid("hil_controller") <= 0)
            return;
    }

    pid = read_first_pid("hil_controller");
    if (pid > 0)
        kill(pid, SIGKILL);
}

static int start_controller(void)
{
    pid_t pid;

    if (read_first_pid("hil_controller") > 0)
        return 0;

    pid = fork();
    if (pid < 0)
        return -1;
    if (pid > 0)
        return 0;

    setsid();

    int fd = open(CONTROLLER_LOG, O_WRONLY | O_CREAT | O_APPEND, 0644);
    if (fd >= 0) {
        dup2(fd, STDOUT_FILENO);
        dup2(fd, STDERR_FILENO);
        close(fd);
    }

    int nullfd = open("/dev/null", O_RDONLY);
    if (nullfd >= 0) {
        dup2(nullfd, STDIN_FILENO);
        close(nullfd);
    }

    execl(CONTROLLER_PATH, "hil_controller", (char *)NULL);
    _exit(127);
}

static int restart_controller(void)
{
    stop_controller();
    usleep(500000);
    return start_controller();
}

static void set_udp_reuse(int sock)
{
    int yes = 1;
    setsockopt(sock, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));
}

int main(void)
{
    int sock;
    struct sockaddr_in addr;
    char buf[512];

    setbuf(stdout, NULL);
    started_at = time(NULL);

    sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (sock < 0) {
        perror("supervisor socket");
        return 1;
    }
    set_udp_reuse(sock);

    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons(SUPERVISOR_PORT);
    addr.sin_addr.s_addr = INADDR_ANY;

    if (bind(sock, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("supervisor bind");
        close(sock);
        return 1;
    }

    printf("HIL supervisor listening on UDP port %d\n", SUPERVISOR_PORT);
    printf("Commands: ping / status / start-controller / stop-controller / restart-controller / reboot-board\n");

    for (;;) {
        struct sockaddr_in cli;
        socklen_t cli_len = sizeof(cli);
        ssize_t n = recvfrom(sock, buf, sizeof(buf) - 1, 0,
                             (struct sockaddr *)&cli, &cli_len);
        char resp[512];
        const char *status = "ok";

        if (n <= 0)
            continue;
        buf[n] = '\0';

        if (strstr(buf, "\"cmd\":\"ping\"")) {
            status = "ok";
        } else if (strstr(buf, "\"cmd\":\"status\"")) {
            status = "ok";
        } else if (strstr(buf, "\"cmd\":\"start-controller\"")) {
            status = start_controller() == 0 ? "controller_started" : "start_failed";
        } else if (strstr(buf, "\"cmd\":\"stop-controller\"")) {
            stop_controller();
            status = "controller_stopped";
        } else if (strstr(buf, "\"cmd\":\"restart-controller\"")) {
            status = restart_controller() == 0 ? "controller_restarted" : "restart_failed";
        } else if (strstr(buf, "\"cmd\":\"reboot-board\"")) {
            write_json_status(resp, sizeof(resp), "rebooting");
            sendto(sock, resp, strlen(resp), 0, (struct sockaddr *)&cli, cli_len);
            sync();
            execl("/sbin/reboot", "reboot", "-f", (char *)NULL);
            execl("/bin/busybox", "busybox", "reboot", "-f", (char *)NULL);
            status = "reboot_failed";
        } else {
            status = "unknown_command";
        }

        write_json_status(resp, sizeof(resp), status);
        sendto(sock, resp, strlen(resp), 0, (struct sockaddr *)&cli, cli_len);
    }
}
