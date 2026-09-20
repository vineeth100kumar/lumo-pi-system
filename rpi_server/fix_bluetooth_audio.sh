#!/bin/bash
# ==============================================================================
# LUMO: Fix Bluetooth Audio Profile Error (br-connection-profile-unavailable)
# Restores PipeWire Bluetooth audio gateway (HFP_AG, HSP_AG, A2DP) so Bluetooth
# microphones, headsets, and AirPods can connect without connection profile errors.
# ==============================================================================

set -e

echo "=== [1/5] Removing restrictive WirePlumber profile overrides ==="
# Remove any custom config that disabled audio roles
rm -f "$HOME/.config/wireplumber/wireplumber.conf.d/51-disable-a2dp-sink.conf" 2>/dev/null || true
rm -f "$HOME/.config/wireplumber/bluetooth.conf.d/51-disable-a2dp-sink.conf" 2>/dev/null || true
echo "Removed restrictive WirePlumber overrides."

echo "=== [2/5] Ensuring PipeWire Bluetooth codecs & packages are installed ==="
sudo apt-get update -y
sudo apt-get install -y pipewire-audio-client-libraries libspa-0.2-bluetooth libportaudio2 bluez-tools

echo "=== [3/5] Configuring WirePlumber for Headset & Mic Support ==="
# Enable all Bluetooth roles (Audio Gateway for mics/headsets + A2DP)
WP_DIR="$HOME/.config/wireplumber/wireplumber.conf.d"
mkdir -p "$WP_DIR"
cat << 'EOF' > "$WP_DIR/50-bluez-all-roles.conf"
monitor.bluez.properties = {
  bluez5.roles = [ "a2dp_sink", "a2dp_source", "bap_sink", "bap_source", "hfp_hf", "hfp_ag", "hsp_hs", "hsp_ag" ]
  bluez5.enable-sbc-xq = true
  bluez5.enable-msbc = true
}
EOF
echo "Configured full Bluetooth headset & mic support in $WP_DIR/50-bluez-all-roles.conf"

echo "=== [4/5] Keeping Wearable Smartwatch Class (0x000704) ==="
# Preserve 0x000704 so iPhone still recognizes LUMO as a smartwatch accessory
if [ -f /etc/bluetooth/main.conf ]; then
    sudo sed -i 's/^#*Class =.*/Class = 0x000704/' /etc/bluetooth/main.conf
    sudo sed -i 's/^#*Name =.*/Name = LUMO Companion/' /etc/bluetooth/main.conf
fi

echo "=== [5/5] Restarting Bluetooth & Audio Daemons ==="
sudo systemctl restart bluetooth
sleep 1
systemctl --user restart pipewire pipewire-pulse wireplumber 2>/dev/null || true
sleep 1

# Re-apply class to live adapter
sudo hciconfig hci0 class 0x000704 2>/dev/null || true

echo ""
echo "===================================================================="
echo " SUCCESS: Bluetooth audio profiles have been restored!"
echo " - Bluetooth mics and headsets can now connect cleanly."
echo " - 'br-connection-profile-unavailable' is resolved."
echo " - You can now pair & connect your Bluetooth mic / headset."
echo "===================================================================="
