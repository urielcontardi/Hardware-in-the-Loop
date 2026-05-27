#!/usr/bin/env python3
"""Watchdog for hil_controller on EBAZ4205.
Pings UDP 5005 every 30 s; if unresponsive twice in a row, kills the
controller via SSH — inittab respawn on the board restarts it automatically.
"""
import socket, time, subprocess, logging, sys

BOARD     = "192.168.15.8"
PORT      = 5005
INTERVAL  = 30
THRESHOLD = 2
SSH_OPTS  = ["-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5"]

logging.basicConfig(stream=sys.stdout, level=logging.INFO,
                    format="%(asctime)s hil-watchdog %(message)s",
                    datefmt="%Y-%m-%dT%H:%M:%S")

def ping():
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
    logging.warning("hil_controller hung — killing via SSH (inittab respawns)")
    try:
        r = subprocess.run(
            ["sshpass", "-p", "1234", "ssh"] + SSH_OPTS + [f"petalinux@{BOARD}",
             'PID=$(ps w | grep "[h]il_controller" | awk \'{print $1}\' | head -1);'
             '[ -n "$PID" ] && echo 1234 | sudo -S kill -9 "$PID" 2>/dev/null'
             ' && echo "killed $PID" || echo "not found"'],
            timeout=15, capture_output=True, text=True)
        logging.info("SSH: %s", (r.stdout + r.stderr).strip()[:80])
    except Exception as e:
        logging.error("SSH failed: %s", e)

fails = 0
logging.info("Watching %s:%d every %ds (threshold=%d)", BOARD, PORT, INTERVAL, THRESHOLD)
while True:
    time.sleep(INTERVAL)
    if ping():
        if fails: logging.info("5005 recovered")
        fails = 0
    else:
        fails += 1
        logging.warning("5005 unresponsive (%d/%d)", fails, THRESHOLD)
        if fails >= THRESHOLD:
            restart()
            fails = 0
            time.sleep(5)
