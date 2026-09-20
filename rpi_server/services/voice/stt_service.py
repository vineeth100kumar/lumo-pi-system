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

    async def transcribe_wav(self, wav_bytes: bytes) -> Optional[str]:
        """Sends an in-memory WAV buffer to Groq Whisper for sub-200ms transcription."""
        if not self.is_configured():
            logger.warning("GROQ_API_KEY is not set. Cannot transcribe audio.")
            return None

        if not wav_bytes or len(wav_bytes) < 44: # Empty WAV header
            return None

        t0 = time.time()
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}"
            }
            files = {
                "file": ("audio.wav", wav_bytes, "audio/wav")
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
