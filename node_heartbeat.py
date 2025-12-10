#!/usr/bin/env python3
import json
import os
import time
import subprocess
from datetime import datetime

CONFIG_PATH = "/home/pi/config.json"      # adjust if yours lives somewhere else
LOG_PATH = "/home/pi/heartbeat.log"


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_PATH, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_config() -> dict:
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def ping_host(ip: str, timeout: int) -> bool:
    """Return True if host responds to a single ping."""
    cmd = ["ping", "-c", "1", "-W", str(timeout), ip]
    result = subprocess.run(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    return result.returncode == 0


def send_heartbeat(node_id: str, user: str, host: str, heartbeat_dir: str) -> bool:
    """
    Create/refresh a heartbeat file on the supervisor using SSH.
    File will be: <heartbeat_dir>/<node_id>.alive
    """
    remote_cmd = f"mkdir -p {heartbeat_dir} && touch {heartbeat_dir}/{node_id}.alive"
    ssh_cmd = ["ssh", f"{user}@{host}", remote_cmd]

    result = subprocess.run(
        ssh_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    return result.returncode == 0


def main():
    cfg = load_config()
    node_id = cfg["global"]["node_id"]

    sup_cfg = cfg["supervisor"]
    sup_host = sup_cfg["host"]
    sup_user = sup_cfg.get("user", "pi")
    heartbeat_dir = sup_cfg["heartbeat_dir"]
    interval = int(sup_cfg.get("heartbeat_interval", 60))
    ping_timeout = int(sup_cfg.get("ping_timeout", 2))

    log(f"Starting heartbeat for {node_id} to {sup_user}@{sup_host}")

    while True:
        # 1) Check if supervisor is reachable
        if not ping_host(sup_host, ping_timeout):
            log(f"Supervisor {sup_host} not reachable (ping failed).")
            time.sleep(interval)
            continue

        # 2) Try to update heartbeat file via SSH
        if send_heartbeat(node_id, sup_user, sup_host, heartbeat_dir):
            log(f"Heartbeat sent for {node_id}.")
        else:
            log(f"FAILED to send heartbeat for {node_id} (SSH error).")

        time.sleep(interval)


if __name__ == "__main__":
    main()
