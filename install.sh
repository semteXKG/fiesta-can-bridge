#!/usr/bin/env bash
# install.sh — deploy fiesta-can-bridge tools to the Raspberry Pi (carpi)
#
# Run on the Pi as root:
#   sudo bash install.sh
#
# Or deploy remotely from a dev machine:
#   ssh semtex@10.0.0.211 'sudo bash -s' < install.sh

set -euo pipefail

INSTALL_DIR="/usr/local/lib/fiesta-can-bridge"
BIN_DIR="/usr/local/bin"
SERVICE_DIR="/etc/systemd/system"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Installing fiesta-can-bridge to ${INSTALL_DIR}"

install -d "${INSTALL_DIR}"
install -m 0755 "${SCRIPT_DIR}/can-poller.py"         "${INSTALL_DIR}/can-poller.py"
install -m 0755 "${SCRIPT_DIR}/can-bridge-starter.py" "${INSTALL_DIR}/can-bridge-starter.py"

# Wrapper script so the tool is on PATH without a .py suffix
cat > "${BIN_DIR}/can-dashboard" <<'EOF'
#!/usr/bin/env bash
exec python3 /usr/local/lib/fiesta-can-bridge/can-bridge-starter.py "$@"
EOF
chmod 0755 "${BIN_DIR}/can-dashboard"

echo "==> Installing systemd service"
install -m 0644 "${SCRIPT_DIR}/etc/systemd/system/can-bridge.service" \
    "${SERVICE_DIR}/can-bridge.service"
systemctl daemon-reload
systemctl enable --now can-bridge.service

echo ""
echo "Done. Tool available:"
echo "  can-dashboard   — auto-discovers WiCAN device and starts live CAN monitor"
echo ""
echo "Service management:"
echo "  systemctl status can-bridge"
echo "  journalctl -u can-bridge -f"
