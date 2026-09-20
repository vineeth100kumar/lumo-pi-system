import io
import os
import time
import math
import shutil
import asyncio
import logging
import tempfile
from typing import Optional, Callable
try:
    import edge_tts
    HAS_EDGE_TTS = True
except ImportError:
    HAS_EDGE_TTS = False

from config import VOICE_NAME
from services.voice.voice_state import VoiceState, VoiceStateManager

logger = logging.getLogger("TTSService")

class TTSService:
    """British Voice Synthesizer using Edge-TTS ('en-GB-RyanNeural').
    Generates natural, crisp speech and coordinates playback with
    dynamic audio volume envelopes to animate LUMO's eyes and NeoPixels.
    """
    def __init__(self, voice: str = VOICE_NAME):
        self.voice = voice or "en-GB-RyanNeural"
        self.last_audio_bytes: bytes = b""
        self.last_text: str = ""
        self.is_speaking = False
        self._player_bin = self._detect_player()
        logger.info(f"TTSService initialized with voice '{self.voice}'. Local player: {self._player_bin or 'Web Client Only'}")

    def _detect_player(self) -> Optional[str]:
        """Finds available audio playback binary on the host system."""
        candidates = ["pw-play", "mpv", "mpg123", "ffplay", "paplay"]
        for c in candidates:
            path = shutil.which(c)
            if path:
                return path
        return None

    async def synthesize(self, text: str) -> bytes:
        """Synthesizes text to MP3 audio bytes in memory."""
        if not text or not text.strip():
            return b""

        if not HAS_EDGE_TTS:
            logger.warning("edge-tts library is not installed. Spoken voice audio is skipped.")
            return b""

        t0 = time.time()
        try:
            # en-GB-RyanNeural delivers the quintessential British Jarvis persona
            communicate = edge_tts.Communicate(text.strip(), self.voice, rate="+2%", pitch="+0Hz")
            mp3_stream = io.BytesIO()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    mp3_stream.write(chunk["data"])

            audio_data = mp3_stream.getvalue()
            elapsed = (time.time() - t0) * 1000.0
            logger.info(f"Synthesized {len(text)} chars ({len(audio_data)} bytes MP3) in {elapsed:.1f}ms")
            self.last_audio_bytes = audio_data
            self.last_text = text
            return audio_data

        except Exception as e:
            logger.error(f"Failed to synthesize TTS via Edge-TTS: {e}")
            return b""

    async def speak(
        self,
        text: str,
        voice_state: Optional[VoiceStateManager] = None,
        on_volume_tick: Optional[Callable[[float], None]] = None
    ) -> bytes:
        """Synthesizes speech and handles synchronized audio playback with visual volume pulses."""
        if not text or not text.strip():
            return b""

        clean_text = text.strip()
        audio_data = await self.synthesize(clean_text)
        if not audio_data:
            return b""

        self.is_speaking = True

        # Estimate duration based on word count (~2.8 words/sec) + min 1.2s
        words = len(clean_text.split())
        est_duration = max(1.2, words / 2.7)

        # Temporary file in /dev/shm (RAM tmpfs on Linux, avoids SD card wear)
        temp_dir = "/dev/shm" if os.path.exists("/dev/shm") else tempfile.gettempdir()
        temp_path = os.path.join(temp_dir, f"lumo_speech_{int(time.time()*1000)}.mp3")

        play_proc = None
        try:
            with open(temp_path, "wb") as f:
                f.write(audio_data)

            # Launch player if available
            if self._player_bin:
                try:
                    if "mpv" in self._player_bin:
                        cmd = [self._player_bin, "--no-video", "--really-quiet", temp_path]
                    elif "ffplay" in self._player_bin:
                        cmd = [self._player_bin, "-nodisp", "-autoexit", "-loglevel", "quiet", temp_path]
                    elif "mpg123" in self._player_bin:
                        cmd = [self._player_bin, "-q", temp_path]
                    elif "pw-play" in self._player_bin:
                        cmd = [self._player_bin, temp_path]
                    else:
                        cmd = [self._player_bin, temp_path]

                    play_proc = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL
                    )
                except Exception as pe:
                    logger.debug(f"Could not spawn local player: {pe}")
                    play_proc = None

            # Animate speech volume envelope in sync with playback
            t_start = time.time()
            if voice_state:
                await voice_state.set_state(VoiceState.SPEAKING, subtitle=clean_text, volume=0.5)

            while (time.time() - t_start) < est_duration:
                if play_proc and play_proc.returncode is not None:
                    break

                elapsed = time.time() - t_start
                # Natural undulating speech envelope
                vol = 0.35 + 0.50 * abs(math.sin(elapsed * 11.0) * math.cos(elapsed * 5.2))

                if voice_state:
                    await voice_state.set_state(VoiceState.SPEAKING, subtitle=clean_text, volume=round(vol, 2))

                if on_volume_tick:
                    try:
                        on_volume_tick(vol)
                    except Exception:
                        pass

                await asyncio.sleep(0.04) # 25 FPS update rate

            if play_proc and play_proc.returncode is None:
                try:
                    await asyncio.wait_for(play_proc.wait(), timeout=1.5)
                except asyncio.TimeoutError:
                    try:
                        play_proc.kill()
                    except Exception:
                        pass

        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            self.is_speaking = False

        return audio_data
