#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo $0"
  exit 1
fi

read -rp "Mesh interface (batman) [bat0]: " MESH_IF
MESH_IF=${MESH_IF:-bat0}

read -rp "Uplink internet interface [wlan1]: " UPLINK_IF
UPLINK_IF=${UPLINK_IF:-wlan1}

read -rp "Supervisor mesh IP/CIDR [10.42.0.30/16]: " MESH_IPCIDR
MESH_IPCIDR=${MESH_IPCIDR:-10.42.0.30/16}

MESH_IP="${MESH_IPCIDR%/*}"
MESH_PREFIX="${MESH_IPCIDR#*/}"

if [[ "$MESH_PREFIX" == "16" ]]; then
  DHCP_RANGE_START="10.42.0.50"
  DHCP_RANGE_END="10.42.0.200"
  DHCP_MASK="255.255.0.0"
  ALLOW_SUBNET="10.42.0.0/16"
elif [[ "$MESH_PREFIX" == "24" ]]; then
  NET_BASE="$(echo "$MESH_IP" | awk -F. '{print $1"."$2"."$3}')"
  DHCP_RANGE_START="${NET_BASE}.50"
  DHCP_RANGE_END="${NET_BASE}.200"
  DHCP_MASK="255.255.255.0"
  ALLOW_SUBNET="${NET_BASE}.0/24"
else
  DHCP_RANGE_START="$MESH_IP"
  DHCP_RANGE_END="$MESH_IP"
  DHCP_MASK="255.255.255.0"
  ALLOW_SUBNET="$MESH_IPCIDR"
fi

echo
echo "=== Summary ==="
echo "Mesh IF:      $MESH_IF"
echo "Uplink IF:    $UPLINK_IF"
echo "Mesh IP/CIDR: $MESH_IPCIDR"
echo "DHCP range:   $DHCP_RANGE_START - $DHCP_RANGE_END ($DHCP_MASK)"
echo "Chrony allow: $ALLOW_SUBNET"
echo

echo "[1/9] Checking and installing required packages..."

# Function to check if package is installed
is_installed() {
    dpkg -l "$1" 2>/dev/null | grep -q "^ii"
}

# Track what needs to be installed
PACKAGES_TO_INSTALL=()

if ! is_installed iptables; then
    echo "  - iptables not found, will install"
    PACKAGES_TO_INSTALL+=("iptables")
else
    echo "  - iptables already installed ✓"
fi

if ! is_installed iptables-persistent; then
    echo "  - iptables-persistent not found, will install"
    PACKAGES_TO_INSTALL+=("iptables-persistent")
else
    echo "  - iptables-persistent already installed ✓"
fi

if ! is_installed dnsmasq; then
    echo "  - dnsmasq not found, will install"
    PACKAGES_TO_INSTALL+=("dnsmasq")
else
    echo "  - dnsmasq already installed ✓"
fi

if ! is_installed chrony; then
    echo "  - chrony not found, will install"
    PACKAGES_TO_INSTALL+=("chrony")
else
    echo "  - chrony already installed ✓"
fi

if ! is_installed conntrack; then
    echo "  - conntrack not found, will install"
    PACKAGES_TO_INSTALL+=("conntrack")
else
    echo "  - conntrack already installed ✓"
fi

# Only run apt-get if we have packages to install
if [ ${#PACKAGES_TO_INSTALL[@]} -gt 0 ]; then
    echo "  Installing: ${PACKAGES_TO_INSTALL[*]}"
    apt-get update -y
    apt-get install -y "${PACKAGES_TO_INSTALL[@]}" || true
else
    echo "  All required packages already installed, skipping apt-get"
fi

echo "[2/9] Stop services for clean configuration..."
systemctl stop dnsmasq || true
systemctl stop chrony || true

echo "[3/9] Writing dnsmasq config for mesh DHCP/DNS..."
cat >/etc/dnsmasq.d/batman-mesh.conf <<EOF
# Listen only on mesh interface
interface=$MESH_IF
bind-interfaces

# Don't forward short names
domain-needed
bogus-priv

# DHCP settings
dhcp-range=$DHCP_RANGE_START,$DHCP_RANGE_END,$DHCP_MASK,12h
dhcp-option=option:router,$MESH_IP
dhcp-option=option:dns-server,$MESH_IP
dhcp-option=option:ntp-server,$MESH_IP

# Faster DHCP response
dhcp-authoritative

# Log DHCP transactions
log-dhcp

# Don't read /etc/hosts
no-hosts

# Don't read /etc/resolv.conf (we're the DNS server)
no-resolv

# Forward DNS to Google (or your preferred DNS)
server=8.8.8.8
server=8.8.4.4
EOF

echo "[4/9] Configuring chrony to serve time to mesh..."
CHRONY_CONF="/etc/chrony/chrony.conf"

# Backup original
cp "$CHRONY_CONF" "$CHRONY_CONF.backup"

# Create new config
cat > "$CHRONY_CONF" <<EOF
# Use public NTP servers
pool pool.ntp.org iburst

# Allow mesh network to query us
allow $ALLOW_SUBNET

# Serve time even if not synced (act as fallback)
local stratum 10

# Allow large time corrections at startup
makestep 1.0 3

# More responsive to time changes
maxupdateskew 100.0

# Standard drift and log files
driftfile /var/lib/chrony/drift
logdir /var/log/chrony

# Let chronyc talk to us
bindcmdaddress 127.0.0.1
bindcmdaddress ::1
EOF

echo "[5/9] Creating gateway setup script..."
cat >/usr/local/sbin/batman-gateway-apply <<'GWSCRIPT'
#!/usr/bin/env bash
set -euo pipefail

MESH_IF="{{MESH_IF}}"
UPLINK_IF="{{UPLINK_IF}}"
MESH_IPCIDR="{{MESH_IPCIDR}}"
MESH_IP="${MESH_IPCIDR%/*}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a /var/log/batman-gateway.log
}

log "=== Starting gateway configuration ==="

# Wait for mesh interface
MAX_WAIT=30
for i in $(seq 1 $MAX_WAIT); do
    if ip link show "$MESH_IF" >/dev/null 2>&1; then
        log "$MESH_IF exists"
        break
    fi
    if [ $i -eq $MAX_WAIT ]; then
        log "ERROR: $MESH_IF not found after ${MAX_WAIT}s"
        exit 1
    fi
    sleep 1
done

# Configure mesh interface
log "Configuring $MESH_IF with IP $MESH_IPCIDR..."
ip link set "$MESH_IF" up || true
sleep 1
ip addr flush dev "$MESH_IF" || true
ip addr add "$MESH_IPCIDR" dev "$MESH_IF"

# Enable IP forwarding
log "Enabling IP forwarding..."
sysctl -w net.ipv4.ip_forward=1 >/dev/null
echo "net.ipv4.ip_forward=1" > /etc/sysctl.d/99-batman-gateway.conf

# Configure iptables for NAT
log "Setting up iptables NAT rules..."

# Set FORWARD policy to ACCEPT
iptables -P FORWARD ACCEPT

# NAT (masquerade) for outgoing traffic
iptables -t nat -C POSTROUTING -o "$UPLINK_IF" -j MASQUERADE 2>/dev/null || \
  iptables -t nat -A POSTROUTING -o "$UPLINK_IF" -j MASQUERADE

# Allow forwarding from mesh to internet
iptables -C FORWARD -i "$MESH_IF" -o "$UPLINK_IF" -j ACCEPT 2>/dev/null || \
  iptables -A FORWARD -i "$MESH_IF" -o "$UPLINK_IF" -j ACCEPT

# Allow established connections back
iptables -C FORWARD -i "$UPLINK_IF" -o "$MESH_IF" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || \
  iptables -A FORWARD -i "$UPLINK_IF" -o "$MESH_IF" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT

# Save iptables rules
log "Saving iptables rules..."
if command -v netfilter-persistent >/dev/null 2>&1; then
    netfilter-persistent save
elif command -v iptables-save >/dev/null 2>&1; then
    iptables-save > /etc/iptables/rules.v4
fi

log "=== Gateway configuration complete ==="
log "Mesh IP: $(ip -4 addr show $MESH_IF | grep inet | awk '{print $2}')"
log "NAT rules: $(iptables -t nat -L POSTROUTING -n | grep -c MASQUERADE) active"

exit 0
GWSCRIPT

python3 - <<PY
from pathlib import Path
p = Path("/usr/local/sbin/batman-gateway-apply")
txt = p.read_text()
txt = txt.replace("{{MESH_IF}}", "${MESH_IF}")
txt = txt.replace("{{UPLINK_IF}}", "${UPLINK_IF}")
txt = txt.replace("{{MESH_IPCIDR}}", "${MESH_IPCIDR}")
p.write_text(txt)
PY

chmod +x /usr/local/sbin/batman-gateway-apply

echo "[6/9] Creating systemd service for gateway..."
cat >/etc/systemd/system/batman-gateway.service <<EOF
[Unit]
Description=Batman Mesh Gateway (NAT + IP assignment)
After=network.target systemd-networkd.service
Before=dnsmasq.service chrony.service
Wants=network.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/batman-gateway-apply
TimeoutStartSec=60
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

echo "[7/9] Updating dnsmasq service to wait for gateway..."
mkdir -p /etc/systemd/system/dnsmasq.service.d
cat >/etc/systemd/system/dnsmasq.service.d/override.conf <<EOF
[Unit]
After=batman-gateway.service
Requires=batman-gateway.service

[Service]
Restart=on-failure
RestartSec=5
EOF

echo "[8/9] Updating chrony service to wait for gateway..."
mkdir -p /etc/systemd/system/chrony.service.d
cat >/etc/systemd/system/chrony.service.d/override.conf <<EOF
[Unit]
After=batman-gateway.service
Requires=batman-gateway.service

[Service]
Restart=always
RestartSec=5
EOF

echo "[9/9] Enabling and starting all services..."
systemctl daemon-reload

# Enable services
systemctl enable batman-gateway.service
systemctl enable dnsmasq.service
systemctl enable chrony.service

# Start in correct order
systemctl start batman-gateway.service
sleep 2
systemctl start dnsmasq.service
systemctl start chrony.service

echo
echo "============================================"
echo "Quick status check:"
echo "============================================"
ip -br a | grep -E "\b$MESH_IF\b" || true
echo
echo "NAT rule:"
iptables -t nat -S | grep MASQUERADE || true
echo
echo "Services:"
systemctl is-active batman-gateway.service && echo "✓ Gateway: ACTIVE" || echo "✗ Gateway: FAILED"
systemctl is-active dnsmasq.service && echo "✓ DHCP/DNS: ACTIVE" || echo "✗ DHCP/DNS: FAILED"
systemctl is-active chrony.service && echo "✓ NTP: ACTIVE" || echo "✗ NTP: FAILED"
echo
echo "Chrony status:"
chronyc tracking || true
echo
echo "============================================"
echo "SETUP COMPLETE!"
echo "============================================"
echo
echo "This supervisor now provides:"
echo "  • DHCP: $DHCP_RANGE_START - $DHCP_RANGE_END"
echo "  • DNS forwarding to internet"
echo "  • NTP time service to $ALLOW_SUBNET"
echo "  • NAT gateway via $UPLINK_IF"
echo
echo "Logs:"
echo "  • Gateway: /var/log/batman-gateway.log"
echo "  • DHCP: journalctl -u dnsmasq -f"
echo "  • NTP: journalctl -u chrony -f"
echo
