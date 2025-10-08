import json
import logging
from logging.handlers import RotatingFileHandler
import os
import time

try:
    import smbus2
    import RPi.GPIO as GPIO
except ImportError:
    print("Install required packages: pip install smbus2 RPi.GPIO")

# --- Load config ---
with open("config.json") as f:
    config = json.load(f)

# --- Setup logging ---
os.makedirs(config["global"]["log_dir"], exist_ok=True)
log_file = os.path.join(config["global"]["log_dir"], "beam_node.log")

handler = RotatingFileHandler(
    log_file,
    maxBytes=config["logging"]["max_size_mb"] * 1024 * 1024,
    backupCount=3
)
logging.basicConfig(level=getattr(logging, config["logging"]["level"].upper()), handlers=[handler])
logger = logging.getLogger(__name__)

# --- BME280 auto-detect ---
def detect_bme280():
    try:
        bus = smbus2.SMBus(1)
        for addr in [0x76, 0x77]:
            try:
                bus.read_byte(addr)
                logger.info(f"BME280 detected at 0x{addr:X}")
                return addr
            except:
                continue
    except Exception as e:
        logger.error(f"I2C error: {e}")
    return None

# --- PIR auto-detect ---
def detect_pir():
    logger.info("Using GPIO 17 for PIR (auto)")
    return 17

# --- Initialize sensors ---
bme_addr = detect_bme280() if config["bme280"]["auto_detect"] else None
pir_pin = detect_pir() if config["pir"]["auto_detect"] else 17

GPIO.setmode(GPIO.BCM)
GPIO.setup(pir_pin, GPIO.IN)

# --- Main loop ---
try:
    while True:
        if config["bme280"]["enabled"] and bme_addr:
            logger.info("Reading BME280 data...")

        if config["pir"]["enabled"] and GPIO.input(pir_pin):
            logger.info("Motion detected by PIR!")

        time.sleep(config["global"]["polling_interval_sec"])
except KeyboardInterrupt:
    logger.info("Stopping node")
finally:
    GPIO.cleanup()

