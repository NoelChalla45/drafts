#!/usr/bin/env python3
import subprocess
import os
import time
import json
from datetime import datetime
from typing import Dict, Tuple, Optional

CONFIG_PATH = "/home/pi/supervisor_config.json"


# -----------------------------
# Helpers
# -----------------------------
def load_config() -> dict:
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def log(message: str, log_file: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {message}"
    print(line)
    try:
        with open(log_file, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def ping_latency(ip: str, count: int = 3) -> Optional[float]:
    """
    Return average latency (ms) if host is reachable, otherwise None.
    """
    cmd = ["ping", "-c", str(count), "-W", "1", ip]
    result = subprocess.run(
        cmd, text=True, capture_output=True
    )
    if result.returncode != 0:
        return None

    # Look for the "rtt min/avg/max/mdev = ..." line
    for line in result.stdout.splitlines():
        if "min/avg/max" in line:
            parts = line.split("=")[-1].strip().split("/")
            try:
                avg_ms = float(parts[1])
                return avg_ms
            except (IndexError, ValueError):
                return None
    return None


def rsync_data(
    ip: str,
    hostname: str,
    supervisor_data_dir: str,
    remote_data_path: str,
    max_retries: int,
    retry_delay: int,
    backoff_factor: float,
    log_file: str,
) -> bool:
    """Sync remote data folder from node to supervisor, with retry logic."""
    dest_dir = os.path.join(supervisor_data_dir, hostname)
    os.makedirs(dest_dir, exist_ok=True)

    rsync_cmd = [
        "rsync", "-avz", "--partial", "--timeout=20",
        f"pi@{ip}:{remote_data_path}/",  # remote source
        dest_dir                         # local destination
    ]

    attempt = 1
    delay = retry_delay

    while attempt <= max_retries:
        log(f"Attempt {attempt}/{max_retries} to sync data from {hostname} ({ip})", log_file)
        result = subprocess.run(
            rsync_cmd, text=True, capture_output=True
        )

        if result.returncode == 0:
            log(f"Successfully synced data from {hostname}.", log_file)
            return True
        else:
            log(
                f"Rsync failed for {hostname} (code {result.returncode}). "
                f"stdout: {result.stdout.strip()} stderr: {result.stderr.strip()}",
                log_file,
            )

            # Check if node is reachable at all
            latency = ping_latency(ip)
            if latency is None:
                log(f"Node {hostname} ({ip}) unreachable (ping failed).", log_file)
            else:
                log(f"Node {hostname} ({ip}) reachable, avg latency {latency:.2f} ms.", log_file)

            if attempt < max_retries:
                log(f"Retrying in {delay} seconds...", log_file)
                time.sleep(delay)
                delay = int(delay * backoff_factor)
            attempt += 1

    log(f"Failed to sync data from {hostname} after {max_retries} attempts.", log_file)
    return False


def has_fresh_heartbeat(
    node_name: str,
    heartbeat_dir: str,
    max_age_sec: int,
    log_file: str,
) -> bool:
    """
    Returns True if there is a heartbeat file for this node that is
    newer than max_age_sec. Otherwise False.
    """
    path = os.path.join(heartbeat_dir, f"{node_name}.alive")
    if not os.path.exists(path):
        log(f"{node_name}: no heartbeat file found in {heartbeat_dir}.", log_file)
        return False

    age = time.time() - os.path.getmtime(path)
    if age > max_age_sec:
        log(
            f"{node_name}: heartbeat too old ({int(age)}s > {max_age_sec}s).",
            log_file,
        )
        return False

    return True


# -----------------------------
# MAIN
# -----------------------------
def main():
    cfg = load_config()

    log_file = cfg.get("log_file", "/home/pi/queue_data_request.log")
    supervisor_data_dir = cfg.get("supervisor_data_dir", "/home/pi/supervisor_data")
    remote_data_path = cfg.get("remote_data_path", "/home/pi/data")

    heartbeat_dir = cfg.get("heartbeat_dir", "/home/pi/supervisor/heartbeats")
    heartbeat_max_age = int(cfg.get("heartbeat_max_age_sec", 120))

    max_retries = int(cfg.get("max_retries", 5))
    retry_delay = int(cfg.get("retry_delay", 5))
    backoff_factor = float(cfg.get("backoff_factor", 2.0))

    max_cycles = int(cfg.get("max_cycles", 3))
    cycle_delay = int(cfg.get("cycle_delay", 60))

    nodes_cfg: Dict[str, Dict] = cfg.get("nodes", {})

    if not nodes_cfg:
        log("No nodes defined in config. Exiting.", log_file)
        return

    log("=== Starting data queue with multi-cycle retry ===", log_file)

    # Track which nodes are still not successfully synced
    remaining = set(nodes_cfg.keys())

    for cycle in range(1, max_cycles + 1):
        if not remaining:
            log("All nodes synced successfully. Stopping early.", log_file)
            break

        log(
            f"--- Cycle {cycle}/{max_cycles} --- "
            f"Remaining nodes: {sorted(remaining)}",
            log_file,
        )

        candidates: Dict[str, Tuple[float, float]] = {}

        # Determine which remaining nodes are worth trying this cycle
        for name in list(remaining):
            node_info = nodes_cfg[name]
            ip = node_info["ip"]
            priority = node_info.get("priority", 999)

            # 1) Check heartbeat freshness
            if not has_fresh_heartbeat(name, heartbeat_dir, heartbeat_max_age, log_file):
                log(f"{name}: skipping this cycle (no fresh heartbeat).", log_file)
                continue

            # 2) Check ping and latency
            latency = ping_latency(ip)
            if latency is None:
                log(f"{name}: heartbeat present but ping failed. Skipping this cycle.", log_file)
                continue

            candidates[name] = (priority, latency)

        if not candidates:
            log("No candidates to sync in this cycle.", log_file)
        else:
            # Sort nodes by priority then latency (strongest connection first)
            sorted_nodes = sorted(
                candidates.items(),
                key=lambda item: (item[1][0], item[1][1]),
            )

            for name, (priority, latency) in sorted_nodes:
                ip = nodes_cfg[name]["ip"]
                log(
                    f"Requesting data from {name} ({ip}), "
                    f"priority={priority}, latency={latency:.2f} ms",
                    log_file,
                )

                success = rsync_data(
                    ip=ip,
                    hostname=name,
                    supervisor_data_dir=supervisor_data_dir,
                    remote_data_path=remote_data_path,
                    max_retries=max_retries,
                    retry_delay=retry_delay,
                    backoff_factor=backoff_factor,
                    log_file=log_file,
                )

                if success:
                    remaining.remove(name)
                else:
                    log(f"{name}: still failed after retries, will try again in a later cycle.", log_file)

                time.sleep(2)  # small delay between nodes

        # Wait before next cycle, if there are still nodes left
        if remaining and cycle < max_cycles:
            log(
                f"End of cycle {cycle}. Unsynced nodes: {sorted(remaining)}. "
                f"Sleeping {cycle_delay} seconds before next cycle...",
                log_file,
            )
            time.sleep(cycle_delay)

    if remaining:
        log(f"FINAL: gave up on nodes: {sorted(remaining)}", log_file)
    else:
        log("FINAL: all nodes synced in this run.", log_file)

    log("=== Data queue complete ===\n", log_file)


if __name__ == "__main__":
    main()
