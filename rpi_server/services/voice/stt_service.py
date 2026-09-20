import io
import time
import logging
from typing import Optional
import httpx
from config import GROQ_API_KEY

logger = logging.getLogger("STTService")

class STTService:
    """Ultra-fast Speech-to-Text using Groq Whisper API (~100ms latency)."""
    def __init__(self, api_key: str = GROQ_API_KEY, model: str = "whisper-large-v3-turbo"):
        self.api_key = api_key
        self.model = model
        self.api_url = "https://api.groq.com/openai/v1/audio/transcriptions"

    def is_configured(self) -> bool:
        return bool(self.api_key and len(self.api_key) > 5)

    @staticmethod
    def detect_format(data: bytes, fallback_mime: Optional[str] = None) -> tuple:
        """Detects container format from audio header magic bytes or fallback mime."""
        if not data:
            return "audio.wav", "audio/wav"
        if data.startswith(b"RIFF"):
            return "audio.wav", "audio/wav"
        elif data.startswith(b"\x1a\x45\xdf\xa3"):
            return "audio.webm", "audio/webm"
        elif data.startswith(b"OggS"):
            return "audio.ogg", "audio/ogg"
        elif data.startswith(b"ID3") or (len(data) > 2 and data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")):
            return "audio.mp3", "audio/mpeg"
        elif (len(data) > 8 and data[4:8] in (b"ftyp", b"moov", b"wide")) or (len(data) > 2 and data[:2] in (b"\xff\xf1", b"\xff\xf9")):
            return "audio.mp4", "audio/mp4"

        if fallback_mime:
            fm = fallback_mime.lower()
            if "webm" in fm:
                return "audio.webm", "audio/webm"
            elif "mp4" in fm or "m4a" in fm or "aac" in fm:
                return "audio.mp4", "audio/mp4"
            elif "ogg" in fm:
                return "audio.ogg", "audio/ogg"
            elif "mp3" in fm or "mpeg" in fm:
                return "audio.mp3", "audio/mpeg"
            elif "wav" in fm:
                return "audio.wav", "audio/wav"

        return "audio.wav", "audio/wav"

    async def transcribe_wav(self, wav_bytes: bytes, mime_type: Optional[str] = None) -> Optional[str]:
        """Sends an in-memory audio buffer (WAV, WebM, MP4, OGG) to Groq Whisper for sub-200ms transcription."""
        if not self.is_configured():
            logger.warning("GROQ_API_KEY is not set. Cannot transcribe audio.")
            return None

        if not wav_bytes or len(wav_bytes) < 32:
            return None

        filename, mime = self.detect_format(wav_bytes, fallback_mime=mime_type)

        t0 = time.time()
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}"
            }
            files = {
                "file": (filename, wav_bytes, mime)
            }
            data = {
                "model": self.model,
                "language": "en",
                "response_format": "json",
                "temperature": "0.0"
            }

            async with httpx.AsyncClient(timeout=8.0) as client:
                res = await client.post(self.api_url, headers=headers, files=files, data=data)

                if res.status_code != 200:
                    logger.error(f"Groq STT HTTP {res.status_code}: {res.text}")
                    return None

                result = res.json()
                text = result.get("text", "").strip()
                elapsed = (time.time() - t0) * 1000.0
                logger.info(f"Groq STT Transcribed in {elapsed:.1f}ms: '{text}'")
                return text

        except Exception as e:
            logger.error(f"Error calling Groq STT: {e}")
            return None
