#!/usr/bin/env python3
"""
Supervisor queue script for BEAM shipped data.

- Uses node_states.json to know:
    - each node's IP
    - whether last transfer failed (transfer_fail)
    - whether node is alive or dead (state)
- Pings nodes to mark them alive/dead.
- Tries to rsync data from nodes that are alive and have NOT failed yet.
- Every RETRY_INTERVAL seconds:
    - Re-pings non-alive nodes to see if they came back.
    - Retries rsync only for nodes that are alive AND transfer_fail == True.

This is basically a single, always-running supervisor that
implements your two-flag logic in a simple way.
"""

import subprocess
import os
import time
import json
from datetime import datetime

# -----------------------------
# CONFIGURATION / PATHS
# -----------------------------

# JSON file where we keep node state + IP + transfer_fail flag
JSON_FILEPATH = "/home/pi/node_states.json"

# Supervisor-side: where all shipped data accumulates
SUPERVISOR_DATA_ROOT = "/home/pi/data"

# Node-side shipping directory (must match node config global.ship_dir)
REMOTE_SHIP_DIR = "/home/pi/shipping"

# Log file on supervisor
LOG_FILE = "/home/pi/queue_data_request.log"

# How often to retry (in seconds)
RETRY_INTERVAL = 600  # 10 minutes


# -----------------------------
# NODE CLASS
# -----------------------------

class Node:
    def __init__(self, name, ip, transfer_fail=False, state="unknown"):
        self.name = name
        self.ip = ip
        self.transfer_fail = transfer_fail   # True if last transfer failed
        self.state = state                   # "alive", "dead", or "unknown"

    def to_dict(self):
        """Convert Node back to a plain dict for JSON saving."""
        return {
            "ip": self.ip,
            "transfer_fail": self.transfer_fail,
            "state": self.state,
        }


# -----------------------------
# LOAD / SAVE NODES JSON
# -----------------------------

def load_nodes(json_filepath):
    """
    Read nodes from JSON file into a list of Node objects.
    JSON format:
    {
      "node1": { "ip": "192.168.1.1", "transfer_fail": false, "state": "unknown" },
      ...
    }
    """
    nodes = []
    if os.path.exists(json_filepath):
        with open(json_filepath, "r") as f:
            data = json.load(f)
            for name, info in data.items():
                ip = info.get("ip")
                transfer = info.get("transfer_fail", False)
                state = info.get("state", "unknown")

                print(
                    f"Loaded node: {name}, IP: {ip}, "
                    f"transfer_fail: {transfer}, state: {state}"
                )

                node = Node(name, ip, transfer, state)
                nodes.append(node)
    else:
        print(f"Node state file not found: {json_filepath}")
    return nodes


def save_nodes(json_filepath, nodes):
    """Write the current Node state back to JSON file."""
    data = {node.name: node.to_dict() for node in nodes}
    with open(json_filepath, "w") as f:
        json.dump(data, f, indent=4)


# -----------------------------
# LOGGING / PING HELPERS
# -----------------------------

def log(message: str) -> None:
    """Append a timestamped message to the log file and print it."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    line = f"[{timestamp}] {message}"
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")
    print(line)


def ping_latency(ip: str, count: int = 3):
    """
    Ping a host and return average latency in ms (None if unreachable).
    """
    try:
        output = subprocess.check_output(
            ["ping", "-c", str(count), "-W", "1", ip],
            stderr=subprocess.DEVNULL,
            universal_newlines=True
        )
        for line in output.splitlines():
            if "avg" in line:
                # Example: rtt min/avg/max/mdev = 0.242/0.256/0.262/0.010 ms
                avg_str = line.split("/")[4]
                return float(avg_str)
    except subprocess.CalledProcessError:
        return None


# -----------------------------
# RSYNC OF SHIPPED DATA (NO ZIPS)
# -----------------------------

def rsync_shipped_data(ip: str, hostname: str) -> bool:
    """
    Pull everything from the node's shipping dir directly into:
        /home/pi/data/

    Nodes ship folders like:
        data-<hostname>-<timestamp>/

    These get copied straight into /home/pi/data, and because
    names include timestamps, new pulls append instead of overwrite.

    Returns True on success, False on failure.
    """
    dest_dir = SUPERVISOR_DATA_ROOT  # /home/pi/data
    os.makedirs(dest_dir, exist_ok=True)

    rsync_cmd = [
        "rsync",
        "-avz",
        "--partial",
        "--ignore-existing",                # do not overwrite files that already exist
        f"pi@{ip}:{REMOTE_SHIP_DIR}/",      # /home/pi/shipping/ on node
        dest_dir                            # /home/pi/data/ on supervisor
    ]

    try:
        subprocess.run(rsync_cmd, check=True)
        log(f"Pulled shipped data from {hostname} ({ip}) -> {dest_dir}")
        return True
    except subprocess.CalledProcessError:
        log(f"Failed to rsync shipped data from {hostname} ({ip})")
        return False


# -----------------------------
# PING HELPERS
# -----------------------------

def ping_nodes(nodes):
    """Ping all nodes once and set their state to 'alive' or 'dead'."""
    for node in nodes:
        latency = ping_latency(node.ip)
        if latency is not None:
            log(f"Node {node.name} ({node.ip}) latency: {latency} ms")
            node.state = "alive"
        else:
            log(f"Node {node.name} ({node.ip}) is unreachable. Marked as dead.")
            node.state = "dead"


def ping_dead_nodes(nodes):
    """
    Check nodes that are NOT 'alive' (dead/unknown).
    If they respond, mark them alive.
    """
    for node in nodes:
        if node.state != "alive":
            latency = ping_latency(node.ip)
            if latency is not None:
                log(
                    f"Node {node.name} ({node.ip}) is back online "
                    f"with latency: {latency} ms"
                )
                node.state = "alive"


# ------------------------------
# MAIN LOGIC
# ------------------------------

def main():
    log("=== Starting shipped data queue ===")

    # Load nodes from JSON
    nodes = load_nodes(JSON_FILEPATH)

    # Initial classification of nodes as alive/dead
    ping_nodes(nodes)
    save_nodes(JSON_FILEPATH, nodes)

    # First attempt: request data from nodes that are alive and not failed yet
    log("=== Initial data transfer attempt ===")
    for node in nodes:
        log(f"Attempting data transfer from {node.name} ({node.ip})")
        if node.state == "alive" and not node.transfer_fail:
            success = rsync_shipped_data(node.ip, node.name)
            log(f"Node {node.name} transfer success: {success}")
            if not success:
                node.transfer_fail = True
                log(f"Node {node.name}: transfer_fail flag set to True")

    save_nodes(JSON_FILEPATH, nodes)

    # Periodically retry failed nodes forever
    while True:
        log("=== Sleeping before next retry cycle ===")
        time.sleep(RETRY_INTERVAL)

        # Re-ping non-alive nodes to see if they came back
        ping_dead_nodes(nodes)
        save_nodes(JSON_FILEPATH, nodes)

        # Retry failed transfers ONLY for nodes that are alive
        log("=== Retrying failed data transfers ===")
        for node in nodes:
            log(f"Attempting data transfer from {node.name} ({node.ip})")
            if node.state == "alive" and node.transfer_fail:
                success = rsync_shipped_data(node.ip, node.name)
                log(f"Node {node.name} transfer success: {success}")
                if success:
                    node.transfer_fail = False
                    log(f"Node {node.name}: transfer_fail flag cleared")

        save_nodes(JSON_FILEPATH, nodes)


if __name__ == "__main__":
    main()
