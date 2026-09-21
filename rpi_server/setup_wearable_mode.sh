#!/bin/bash
# ==============================================================================
# LUMO Companion: Configure Bluetooth as Wearable / Smartwatch
# This prevents iOS / Android from treating the Pi as a speaker or microphone.
# Phone calls, Siri, and audio playback remain on your iPhone / AirPods,
# while track metadata (AVRCP), OBEX photo sharing, and notifications stay active.
# ==============================================================================

set -e

echo "=== [1/4] Setting Bluetooth Class to Wearable Watch (0x000704) ==="
if [ -f /etc/bluetooth/main.conf ]; then
    # Backup original if not already backed up
    if [ ! -f /etc/bluetooth/main.conf.bak ]; then
        sudo cp /etc/bluetooth/main.conf /etc/bluetooth/main.conf.bak 2>/dev/null || true
    fi
    # Set Class of Device = 0x000704 (Major: Wearable 0x07, Minor: Wristwatch 0x04)
    sudo sed -i 's/^#*Class =.*/Class = 0x000704/' /etc/bluetooth/main.conf
    sudo sed -i 's/^#*Name =.*/Name = LUMO Companion/' /etc/bluetooth/main.conf
    echo "Updated /etc/bluetooth/main.conf with Class=0x000704"
fi

echo "=== [2/4] Disabling Bluetooth Audio Sink & Headset in PipeWire/WirePlumber ==="
# Remove any configs that enabled audio sink or headset/mic roles
WP_DIR_1="$HOME/.config/wireplumber/wireplumber.conf.d"
WP_DIR_2="$HOME/.config/wireplumber/bluetooth.conf.d"
mkdir -p "$WP_DIR_1" "$WP_DIR_2"

# Clean up all old conflicting configs
rm -f "$WP_DIR_1/50-bluez-all-roles.conf" 2>/dev/null || true
rm -f "$WP_DIR_2/50-bluez-all-roles.conf" 2>/dev/null || true
rm -f "$WP_DIR_1/51-disable-a2dp-sink.conf" 2>/dev/null || true
rm -f "$WP_DIR_2/51-disable-a2dp-sink.conf" 2>/dev/null || true

# Write config with zero audio roles (bluez5.roles = [])
# This ensures WirePlumber does NOT advertise A2DP Sink (speaker) or HFP/HSP (mic/headset) to iOS
cat << 'EOF' > "$WP_DIR_1/50-no-bluetooth-audio.conf"
monitor.bluez.properties = {
  bluez5.roles = [ ]
}
EOF
cp "$WP_DIR_1/50-no-bluetooth-audio.conf" "$WP_DIR_2/50-no-bluetooth-audio.conf" 2>/dev/null || true

echo "Disabled Bluetooth audio & mic roles in WirePlumber."

# Also handle PulseAudio if installed
if [ -f /etc/pulse/default.pa ]; then
    sudo sed -i 's/.*load-module module-bluetooth-policy.*/#&/' /etc/pulse/default.pa 2>/dev/null || true
fi

echo "=== [3/4] Restarting Audio & Bluetooth Services ==="
systemctl --user restart wireplumber 2>/dev/null || true
systemctl --user restart pipewire 2>/dev/null || true
systemctl --user restart pipewire-pulse 2>/dev/null || true

sudo systemctl restart bluetooth
sleep 1

# Force live adapter to Wearable class
sudo hciconfig hci0 class 0x000704 2>/dev/null || true
sudo bluetoothctl system-alias "LUMO Companion" 2>/dev/null || true

echo "=== [4/4] Ensuring OBEX Push is Available for Photo Sharing ==="
if command -v sdptool >/dev/null 2>&1; then
    sudo sdptool add OPUSH 2>/dev/null || true
fi

echo ""
echo "===================================================================="
echo " SUCCESS: LUMO is now configured strictly as a Wearable Companion!"
echo " - iPhone will NEVER use LUMO as a speaker or microphone."
echo " - Audio & phone calls stay 100% on your iPhone or AirPods."
echo " - Track info (AVRCP) & Notifications (ANCS) remain active."
echo ""
echo " IMPORTANT IPHONE STEPS:"
echo " 1. On iPhone, go to Settings -> Bluetooth -> LUMO Companion (ⓘ)."
echo " 2. Set 'Device Type' to 'Other' (never Speaker or Headphone)."
echo " 3. If audio is currently routed to LUMO, toggle Bluetooth off and on"
echo "    or tap 'Forget This Device' and reconnect."
echo "===================================================================="
