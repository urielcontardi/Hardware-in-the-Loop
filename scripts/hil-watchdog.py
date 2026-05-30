#!/usr/bin/env python3
"""Watchdog for hil_controller on EBAZ4205.
Pings UDP 5005 every 30 s; if unresponsive twice in a row, kills and
restarts the controller via SSH.
"""
import socket, time, subprocess, logging, sys

BOARD        = "192.168.15.8"
PORT         = 5005
INTERVAL     = 30
THRESHOLD    = 2
CONTROLLER   = "/home/petalinux/hil_controller"
LOG_FILE     = "/tmp/hil_controller.log"
SSH_OPTS     = ["-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5",
                "-o", "BatchMode=yes"]

logging.basicConfig(stream=sys.stdout, level=logging.INFO,
                    format="%(asctime)s hil-watchdog %(message)s",
                    datefmt="%Y-%m-%dT%H:%M:%S")

def ssh(cmd: str, timeout: int = 20) -> str:
    r = subprocess.run(
        ["sshpass", "-p", "1234", "ssh"] + SSH_OPTS + [f"petalinux@{BOARD}", cmd],
        timeout=timeout, capture_output=True, text=True)
    return (r.stdout + r.stderr).strip()

def ping() -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(2)
    try:
        s.sendto(b'{"cmd":"ping"}', (BOARD, PORT))
        s.recvfrom(256)
        return True
    except Exception:
        return False
    finally:
        s.close()

def restart():
    logging.warning("hil_controller unresponsive — killing and restarting")
    try:
        # Kill any running instance
        out = ssh(
            'PID=$(ps w | grep "[h]il_controller" | awk \'{print $1}\' | head -1);'
            '[ -n "$PID" ] && echo 1234 | sudo -S kill -9 "$PID" 2>/dev/null'
            ' && echo "killed $PID" || echo "not running"'
        )
        logging.info("kill: %s", out[:80])

        time.sleep(2)

        # Restart as background daemon, output goes to log file
        out = ssh(
            f'echo 1234 | sudo -S sh -c '
            f'"nohup {CONTROLLER} >> {LOG_FILE} 2>&1 &"'
            f' && echo "started"'
        )
        logging.info("start: %s", out[:80])

    except subprocess.TimeoutExpired:
        logging.error("SSH timed out during restart")
    except Exception as e:
        logging.error("restart failed: %s", e)

fails = 0
logging.info("Watching %s:%d every %ds (threshold=%d)", BOARD, PORT, INTERVAL, THRESHOLD)
while True:
    time.sleep(INTERVAL)
    if ping():
        if fails:
            logging.info("5005 recovered after %d failure(s)", fails)
        fails = 0
    else:
        fails += 1
        logging.warning("5005 unresponsive (%d/%d)", fails, THRESHOLD)
        if fails >= THRESHOLD:
            restart()
            fails = 0
            time.sleep(10)  # allow time for restart before next ping
