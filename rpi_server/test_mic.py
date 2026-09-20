#!/usr/bin/env python3
"""LUMO JARVIS Microphone & Audio Diagnostic Tool
Tests local microphone capture, audio volume levels, Groq STT, and Jarvis speech.
Usage:
    python3 test_mic.py
"""

import sys
import time
import math
import asyncio

print("=" * 60)
print("  LUMO JARVIS Microphone & Audio Diagnostic Tool")
print("=" * 60)

# Step 1: Check sounddevice and PortAudio
try:
    import sounddevice as sd
    import numpy as np
    print("[✓] sounddevice and numpy are installed.")
except ImportError as e:
    print(f"\n[!] Error importing audio libraries: {e}")
    print("\nTo fix on Raspberry Pi:")
    print("  sudo apt update && sudo apt install -y libportaudio2")
    print("  pip install sounddevice numpy")
    sys.exit(1)

# Step 2: List audio devices
print("\n[+] Scanning audio input devices...")
devices = sd.query_devices()
input_devices = []
default_idx = sd.default.device[0] if sd.default.device else -1

for idx, dev in enumerate(devices):
    if dev.get("max_input_channels", 0) > 0:
        is_def = (idx == default_idx)
        star = " ★ [DEFAULT]" if is_def else ""
        print(f"  [{idx}] {dev['name']} ({dev['max_input_channels']} in, {int(dev['default_samplerate'])}Hz){star}")
        input_devices.append((idx, dev))

if not input_devices:
    print("\n[!] No audio input devices found!")
    print("    If using a Bluetooth mic, ensure it is connected:")
    print("    bluetoothctl info")
    print("    pactl list sources short")
    sys.exit(1)

# Step 3: Select device
selected_dev = None
print("\nPress ENTER to test the default mic, or type the device number:")
try:
    choice = input("Device choice [default]: ").strip()
    if choice.isdigit() and int(choice) < len(devices):
        selected_dev = int(choice)
except (KeyboardInterrupt, EOFError):
    print("\nExiting.")
    sys.exit(0)

dev_name = sd.query_devices(selected_dev)['name'] if selected_dev is not None else "System Default"
dev_rate = int(sd.query_devices(selected_dev)['default_samplerate']) if selected_dev is not None else 16000
# Prefer 16000Hz if supported, else native rate
sample_rate = 16000
try:
    sd.check_input_settings(device=selected_dev, samplerate=sample_rate, channels=1, dtype='int16')
except Exception:
    sample_rate = dev_rate

print(f"\n[+] Selected device: '{dev_name}' ({sample_rate}Hz mono)")
print("\nGet ready to speak into the microphone for 4 seconds...")
for countdown in [3, 2, 1]:
    print(f"  Starting in {countdown}...", end="\r", flush=True)
    time.sleep(1)

print("\n🎙️  RECORDING NOW! Speak clearly into your mic! (e.g. 'Jarvis, set optics to cyan')...")

# Step 4: Record audio buffer
duration_sec = 4.0
try:
    audio_data = sd.rec(
        int(duration_sec * sample_rate),
        samplerate=sample_rate,
        channels=1,
        dtype='int16',
        device=selected_dev
    )
    sd.wait()
except Exception as e:
    print(f"\n[!] Recording failed: {e}")
    sys.exit(1)

print("[✓] Recording complete!")

# Step 5: Check audio volume (RMS)
raw_bytes = audio_data.tobytes()
count = len(raw_bytes) // 2
import struct
shorts = struct.unpack(f"<{count}h", raw_bytes)
sum_sq = sum(s * s for s in shorts)
rms = math.sqrt(sum_sq / count) / 32768.0

vu_blocks = int(min(1.0, rms * 15) * 30)
vu_bar = "█" * vu_blocks + "░" * (30 - vu_blocks)
print(f"\n[+] Audio Signal Level:")
print(f"    RMS: {rms:.4f}  |{vu_bar}|")

if rms < 0.005:
    print("    [!] Warning: Signal level is very low or silent.")
    print("        Check mic volume or mute switch on your Bluetooth headset.")
else:
    print("    [✓] Clear audio signal detected!")

# Step 6: Test Groq Whisper STT & Jarvis Brain
print("\n[+] Testing Groq Whisper STT...")
from config import GROQ_API_KEY
if not GROQ_API_KEY:
    print("[!] GROQ_API_KEY is not set in .env! Cannot transcribe.")
    sys.exit(0)

from services.voice.audio_capture import AudioCaptureService
from services.voice.stt_service import STTService
from services.voice.jarvis_brain import JarvisBrain

wav_bytes = AudioCaptureService.pcm_to_wav(raw_bytes, sample_rate=sample_rate, channels=1)

async def test_full_pipeline():
    stt = STTService()
    t0 = time.time()
    transcript = await stt.transcribe_wav(wav_bytes)
    t_stt = (time.time() - t0) * 1000

    if not transcript:
        print("[!] No speech recognized by Whisper.")
        return

    print(f"    Transcribed in {t_stt:.1f}ms: \"{transcript}\"")

    print("\n[+] Asking JARVIS Brain...")
    brain = JarvisBrain()
    t1 = time.time()
    reply = await brain.ask(transcript)
    t_brain = (time.time() - t1) * 1000

    print(f"    Jarvis Reply ({t_brain:.1f}ms): \"{reply}\"")

    # Step 7: Test TTS Audio Playback
    print("\n[+] Synthesizing JARVIS British Voice...")
    from services.voice.tts_service import TTSService
    tts = TTSService()
    t2 = time.time()
    audio = await tts.synthesize(reply)
    t_tts = (time.time() - t2) * 1000
    print(f"    Generated {len(audio)} bytes speech in {t_tts:.1f}ms")

    print(f"\n⚡ TOTAL LATENCY: {(t_stt + t_brain + t_tts):.1f}ms (Target < 1000ms)")
    print("\n[✓] Diagnostic Complete! All systems nominal.")

asyncio.run(test_full_pipeline())
