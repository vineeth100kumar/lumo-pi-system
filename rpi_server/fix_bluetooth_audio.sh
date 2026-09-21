#!/bin/bash
# ==============================================================================
# LUMO: Configure Wearable Mode & Disable Audio Hijacking
# Delegates to setup_wearable_mode.sh to ensure iOS treats LUMO as a smartwatch
# and does not hijack iPhone audio output or microphone input.
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash "$SCRIPT_DIR/setup_wearable_mode.sh"
