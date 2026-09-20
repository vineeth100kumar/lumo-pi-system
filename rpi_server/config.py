import os
from dotenv import load_dotenv

load_dotenv()

# Server Ports & Hostname
WS_PORT = int(os.getenv("WS_PORT", 8765))
HTTP_PORT = int(os.getenv("HTTP_PORT", 8080))
MDNS_NAME = os.getenv("MDNS_NAME", "lumo")

# Spotify API Credentials
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
SPOTIFY_REFRESH_TOKEN = os.getenv("SPOTIFY_REFRESH_TOKEN", "")

# Weather Location Coordinates (Default: Bangalore)
WEATHER_LAT = float(os.getenv("WEATHER_LAT", 13.003648))
WEATHER_LON = float(os.getenv("WEATHER_LON", 77.628993))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Sage (the task manager) is the single store for tasks, reminders and alarms.
# Lumo reads and writes them through Sage's API on the loopback address rather
# than opening its database, so Sage's own rules still apply and the phone app
# hears about every change. See services/sage_client.py.
SAGE_API_URL = os.getenv("SAGE_API_URL", "http://127.0.0.1:8000")
SAGE_REQUEST_TIMEOUT = float(os.getenv("SAGE_REQUEST_TIMEOUT", "8.0"))

# The key lives in exactly one place, Sage's environment file, which systemd
# reads for both services. These two are fallbacks for running main.py by hand.
SAGE_API_KEY = os.getenv("SAGE_API_KEY", "")
SAGE_ENV_FILE = os.getenv("SAGE_ENV_FILE", "/etc/sage/sage.env")
SAGE_SECRET_FILE = os.getenv("SAGE_SECRET_FILE", "/home/pi/sage-os/data/api_secret.txt")

# Alarms are Sage reminders carrying this tag. The tag is how Lumo knows to
# sound the buzzer for one rather than show it as a notification card.
SAGE_ALARM_TAG = os.getenv("SAGE_ALARM_TAG", "alarm")

# How often to re-read the lists from Sage. Live changes arrive over the
# websocket within the second; this is the safety net for a missed event.
SAGE_REFRESH_SECONDS = int(os.getenv("SAGE_REFRESH_SECONDS", "120"))

# Circadian Rhythm Schedule (Hour Thresholds)
HOUR_SLEEP_START = 0    # Midnight
HOUR_SLEEP_END   = 8    # 8:00 AM
HOUR_DROWSY_START = 22  # 10:00 PM

# JARVIS Voice Assistant Settings
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_LLM_MODEL = os.getenv("GROQ_LLM_MODEL", "qwen/qwen3.8-27b")
VOICE_ENABLED = os.getenv("VOICE_ENABLED", "true").lower() == "true"
VOICE_INPUT_DEVICE = os.getenv("VOICE_INPUT_DEVICE", "default")
VOICE_OUTPUT_DEVICE = os.getenv("VOICE_OUTPUT_DEVICE", "default")
VOICE_NAME = os.getenv("VOICE_NAME", "en-GB-RyanNeural")
VOICE_RMS_THRESHOLD = float(os.getenv("VOICE_RMS_THRESHOLD", "0.018"))
VOICE_SILENCE_MS = int(os.getenv("VOICE_SILENCE_MS", "650"))
WAKE_WORD_SENSITIVITY = float(os.getenv("WAKE_WORD_SENSITIVITY", "0.55"))
