#!/bin/bash
# ========================================
# BATMAN-adv Automatic Setup Script (Interactive, Interface-Selectable)
# Tested on Debian / Raspberry Pi OS
# ========================================

set -e

echo "=== BATMAN-adv Setup Script ==="
echo

# --- Ask for configuration with defaults ---
read -p "Enter wireless interface to use (e.g. wlan0, wlan1) [wlan0]: " IFACE
IFACE=${IFACE:-wlan0}

read -p "Enter ad-hoc network name (SSID) [myadhoc]: " NETWORK_NAME
NETWORK_NAME=${NETWORK_NAME:-myadhoc}

read -p "Enter frequency in MHz (e.g. 2412 for channel 1) [2412]: " FREQUENCY
FREQUENCY=${FREQUENCY:-2412}

read -p "Enter static IP for bat0 (e.g. 192.168.1.2/24) [192.168.1.2/24]: " STATIC_IP
STATIC_IP=${STATIC_IP:-192.168.1.2/24}

echo
echo "Using configuration:"
echo "  Interface:  $IFACE"
echo "  SSID:       $NETWORK_NAME"
echo "  Frequency:  $FREQUENCY MHz"
echo "  IP Address: $STATIC_IP"
echo
read -p "Press Enter to continue or Ctrl+C to cancel..."

# --- Create BATMAN startup script ---
echo "[1/4] Creating /usr/local/bin/start-batman.sh ..."
cat <<EOF | sudo tee /usr/local/bin/start-batman.sh >/dev/null
#!/bin/bash
# ========================================
# BATMAN-adv Startup Script
# ========================================

echo "Starting BATMAN-adv mesh setup..."

# Stop and disable conflicting services
systemctl stop wpa_supplicant 2>/dev/null || true
systemctl disable wpa_supplicant 2>/dev/null || true
systemctl stop NetworkManager 2>/dev/null || true
systemctl disable NetworkManager 2>/dev/null || true

# Load BATMAN kernel module
modprobe batman-adv

# Configure wireless interface for ad-hoc mode
ip link set $IFACE down
iw dev $IFACE set type ibss
ip link set $IFACE up
iw dev $IFACE ibss join $NETWORK_NAME $FREQUENCY

# Add interface to BATMAN
batctl if add $IFACE
ip link set up dev bat0

# Assign static IP
ip addr add $STATIC_IP dev bat0

echo "BATMAN-adv setup complete!"
EOF

sudo chmod +x /usr/local/bin/start-batman.sh

# --- Create systemd service ---
echo "[2/4] Creating /etc/systemd/system/batman.service ..."
cat <<EOF | sudo tee /etc/systemd/system/batman.service >/dev/null
[Unit]
Description=BATMAN-adv Mesh Network
After=network.target sys-subsystem-net-devices-$IFACE.device
Wants=sys-subsystem-net-devices-$IFACE.device

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/bash /usr/local/bin/start-batman.sh

[Install]
WantedBy=multi-user.target
EOF

# --- Reload systemd and enable service ---
echo "[3/4] Reloading systemd and enabling service ..."
sudo systemctl daemon-reload
sudo systemctl enable batman.service

# --- Start service immediately ---
echo "[4/4] Starting BATMAN service ..."
sudo systemctl start batman.service

echo
echo "✅ BATMAN-adv setup complete!"
echo "To verify, run: sudo systemctl status batman.service"
echo "Then check mesh neighbors with: sudo batctl n"
