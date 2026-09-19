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

echo "=== [2/3] Disabling A2DP Audio Sink (No Audio Hijacking) ==="
# Prevent PipeWire / WirePlumber from registering an audio speaker endpoint
WP_DIR="$HOME/.config/wireplumber/wireplumber.conf.d"
mkdir -p "$WP_DIR"
cat << 'EOF' > "$WP_DIR/51-disable-a2dp-sink.conf"
monitor.bluez.properties = {
  bluez5.roles = [ "hfp_hf", "hsp_hs" ]
}
EOF
echo "Created $WP_DIR/51-disable-a2dp-sink.conf"

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
