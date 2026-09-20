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

# Alarm & Task File Storage
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ALARM_FILE = os.path.join(BASE_DIR, "alarms.json")
TASK_FILE = os.path.join(BASE_DIR, "tasks.json")

# Circadian Rhythm Schedule (Hour Thresholds)
HOUR_SLEEP_START = 0    # Midnight
HOUR_SLEEP_END   = 8    # 8:00 AM
HOUR_DROWSY_START = 22  # 10:00 PM

# JARVIS Voice Assistant Settings
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
VOICE_ENABLED = os.getenv("VOICE_ENABLED", "true").lower() == "true"
VOICE_INPUT_DEVICE = os.getenv("VOICE_INPUT_DEVICE", "default")
VOICE_OUTPUT_DEVICE = os.getenv("VOICE_OUTPUT_DEVICE", "default")
VOICE_NAME = os.getenv("VOICE_NAME", "en-GB-RyanNeural")
VOICE_RMS_THRESHOLD = float(os.getenv("VOICE_RMS_THRESHOLD", "0.018"))
VOICE_SILENCE_MS = int(os.getenv("VOICE_SILENCE_MS", "650"))
WAKE_WORD_SENSITIVITY = float(os.getenv("WAKE_WORD_SENSITIVITY", "0.55"))
