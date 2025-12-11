#!/usr/bin/env python3
import json, subprocess, time, os
from datetime import datetime

CONFIG_PATH = "/home/pi/supervisor_config.json"
STATE_PATH  = "/home/pi/supervisor_state.json"

def load_json(path):
    with open(path, "r") as f: return json.load(f)

def save_json(path, data):
    with open(path, "w") as f: json.dump(data, f, indent=4)

def log(msg, log_file):
    timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
    line = f"{timestamp} {msg}"
    print(line)
    with open(log_file, "a") as f: f.write(line + "\n")

def ping(ip):
    result = subprocess.run(["ping", "-c", "1", "-W", "1", ip],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    return result.returncode == 0

def rsync_data(ip, name, config, log_file):
    dest_dir = os.path.join(config["supervisor_data_dir"], name)
    os.makedirs(dest_dir, exist_ok=True)

    cmd = [
        "rsync", "-avz", "--partial", "--timeout=20",
        f"pi@{ip}:{config['remote_data_path']}/",
        dest_dir
    ]

    delay = config["retry_delay"]
    for attempt in range(1, config["max_retries"] + 1):
        log(f"{name}: Attempt {attempt} to rsync data (catch-up)", log_file)
        result = subprocess.run(cmd, text=True, capture_output=True)
        if result.returncode == 0:
            log(f"{name}: CATCH-UP SUCCESS", log_file)
            return True

        time.sleep(delay)
        delay = int(delay * config["backoff_factor"])
    return False

def main():
    config = load_json(CONFIG_PATH)
    state  = load_json(STATE_PATH)
    log_file = config["log_file"]

    log("=== 10 MIN HEALTH CHECK ===", log_file)

    for name, info in config["nodes"].items():
        ip = info["ip"]
        is_alive = ping(ip)

        if is_alive and not state[name]["node_alive"]:
            state[name]["node_alive"] = True
            state[name]["last_online_time"] = datetime.now().isoformat()
            log(f"{name}: came ONLINE", log_file)

        if not is_alive and state[name]["node_alive"]:
            state[name]["node_alive"] = False
            state[name]["last_offline_time"] = datetime.now().isoformat()
            log(f"{name}: went OFFLINE", log_file)

    for name, info in config["nodes"].items():
        if state[name]["fail_to_request_data"] and state[name]["node_alive"]:
            log(f"{name}: Flags true, running CATCH-UP", log_file)

            ip = info["ip"]
            success = rsync_data(ip, name, config, log_file)

            if success:
                state[name]["fail_to_request_data"] = False
                log(f"{name}: Catch-up success, flag cleared.", log_file)

    save_json(STATE_PATH, state)
    log("=== HEALTH CHECK COMPLETE ===", log_file)

if __name__ == "__main__":
    main()
