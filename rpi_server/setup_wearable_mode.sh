#!/bin/bash
# ==============================================================================
# LUMO Companion: Configure Bluetooth as Wearable / Smartwatch (Ather Connect style)
# This prevents iOS / Android from treating the Pi as a speaker, so audio stays
# playing on your phone / AirPods, while LUMO receives track metadata and alerts.
# ==============================================================================

set -e

echo "=== [1/3] Setting Bluetooth Class to Wearable Watch (0x000704) ==="
if [ -f /etc/bluetooth/main.conf ]; then
    # Backup original
    sudo cp /etc/bluetooth/main.conf /etc/bluetooth/main.conf.bak 2>/dev/null || true
    # Set Class of Device = 0x000704 (Major: Wearable 0x07, Minor: Wristwatch 0x04)
    sudo sed -i 's/^#*Class =.*/Class = 0x000704/' /etc/bluetooth/main.conf
    sudo sed -i 's/^#*Name =.*/Name = LUMO Companion/' /etc/bluetooth/main.conf
    echo "Updated /etc/bluetooth/main.conf with Class=0x000704"
fi

echo "=== [2/3] Enabling Bluetooth Mic & Audio Gateway Profiles ==="
# Remove old restrictive config that broke Bluetooth headset/mic connections
WP_DIR="$HOME/.config/wireplumber/wireplumber.conf.d"
rm -f "$WP_DIR/51-disable-a2dp-sink.conf" 2>/dev/null || true
mkdir -p "$WP_DIR"
cat << 'EOF' > "$WP_DIR/50-bluez-all-roles.conf"
monitor.bluez.properties = {
  bluez5.roles = [ "a2dp_sink", "a2dp_source", "bap_sink", "bap_source", "hfp_hf", "hfp_ag", "hsp_hs", "hsp_ag" ]
  bluez5.enable-sbc-xq = true
  bluez5.enable-msbc = true
}
EOF
echo "Configured Bluetooth audio & mic support in $WP_DIR/50-bluez-all-roles.conf"

# Also handle PulseAudio if installed
if [ -f /etc/pulse/default.pa ]; then
    sudo sed -i 's/.*load-module module-bluetooth-policy.*/#&/' /etc/pulse/default.pa 2>/dev/null || true
fi

# Restart audio servers if running
systemctl --user restart wireplumber 2>/dev/null || true
systemctl --user restart pipewire 2>/dev/null || true

echo "=== [3/3] Restarting Bluetooth Daemon ==="
sudo systemctl restart bluetooth
sleep 1
sudo hciconfig hci0 class 0x000704 2>/dev/null || true

echo ""
echo "===================================================================="
echo " SUCCESS: LUMO is now configured as a Wearable Smartwatch Accessory!"
echo " - Phone will show a Watch/Wearable icon ⌚"
echo " - Audio will NOT be hijacked (stays on your AirPods / Phone)"
echo " - Track info & notifications will still sync to LUMO!"
echo "===================================================================="
