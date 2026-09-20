import io
import time
import asyncio
import logging
from typing import Optional, Dict, Any

from config import (
    VOICE_ENABLED,
    VOICE_INPUT_DEVICE,
    VOICE_NAME,
    VOICE_RMS_THRESHOLD,
    VOICE_SILENCE_MS
)
from services.voice.voice_state import VoiceState, VoiceStateManager
from services.voice.audio_capture import AudioCaptureService
from services.voice.stt_service import STTService
from services.voice.jarvis_brain import JarvisBrain
from services.voice.tts_service import TTSService

logger = logging.getLogger("VoiceService")

class VoiceService:
    """Master orchestrator for LUMO's JARVIS Voice Assistant Companion.
    Coordinates continuous Bluetooth/USB mic capture, Groq Whisper STT,
    Groq Llama 3.3-70B tool-calling brain, Edge-TTS British speech synthesis,
    and real-time ESP32 hardware synchronization.
    """
    def __init__(
        self,
        hub=None,
        anim_engine=None,
        services: Optional[Dict[str, Any]] = None
    ):
        self.hub = hub
        self.anim_engine = anim_engine
        self.services = services or {}

        # Subsystems
        self.state_mgr = VoiceStateManager(hub=self.hub, anim_engine=self.anim_engine)
        self.stt = STTService()
        self.brain = JarvisBrain(hub=self.hub, services=self.services)
        self.tts = TTSService(voice=VOICE_NAME)

        self.audio_capture = AudioCaptureService(
            sample_rate=16000,
            channels=1,
            rms_threshold=VOICE_RMS_THRESHOLD,
            silence_timeout_ms=VOICE_SILENCE_MS,
            device=VOICE_INPUT_DEVICE
        )

        # Connect audio capture callbacks
        self.audio_capture.on_speech_started = self._handle_speech_started
        self.audio_capture.on_speech_ended = self._handle_speech_ended
        self.audio_capture.on_rms_update = self._handle_rms_update

        self.is_running = False
        self._turn_lock = asyncio.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def update_services(self, services: Dict[str, Any], hub=None):
        """Updates referenced LUMO services and WebSocket hub."""
        self.services.update(services)
        if hub:
            self.hub = hub
            self.state_mgr.hub = hub
        self.brain.set_services(self.services, hub=self.hub)

    def start(self, loop: Optional[asyncio.AbstractEventLoop] = None):
        """Starts background audio capture if enabled in config."""
        self._loop = loop or asyncio.get_event_loop()
        self.is_running = True

        if VOICE_ENABLED:
            started = self.audio_capture.start_background_stream(loop=self._loop)
            if started:
                logger.info("VoiceService started with live background microphone monitoring.")
            else:
                logger.info("Microphone stream not started (device not connected or sounddevice unavailable). Web Push-to-Talk active.")
        else:
            logger.info("VoiceService background mic listening is disabled in config. Web Push-to-Talk active.")

    def stop(self):
        """Stops background audio capture."""
        self.is_running = False
        self.audio_capture.stop_stream()
        logger.info("VoiceService stopped.")

    def _handle_speech_started(self):
        """Called by AudioCaptureService when user starts speaking into microphone."""
        if self.state_mgr.current_state == VoiceState.IDLE:
            if self._loop:
                asyncio.run_coroutine_threadsafe(
                    self.state_mgr.set_state(VoiceState.LISTENING),
                    self._loop
                )

    def _handle_speech_ended(self, pcm_bytes: bytes):
        """Called by AudioCaptureService when user stops speaking."""
        if not pcm_bytes:
            return

        wav_bytes = AudioCaptureService.pcm_to_wav(
            pcm_bytes,
            sample_rate=self.audio_capture.sample_rate,
            channels=self.audio_capture.channels
        )
        if self._loop:
            asyncio.run_coroutine_threadsafe(
                self.process_voice_turn(wav_bytes),
                self._loop
            )

    def _handle_rms_update(self, rms: float):
        """Tracks live mic volume level."""
        if self.state_mgr.current_state == VoiceState.LISTENING:
            self.state_mgr.current_volume = min(1.0, rms * 4.0)

    async def process_voice_turn(self, audio_bytes: bytes, mime_type: Optional[str] = None) -> Dict[str, Any]:
        """Processes a full conversational turn: STT -> Brain (Tools) -> TTS -> ESP32 sync."""
        async with self._turn_lock:
            # 1. Transition to THINKING
            await self.state_mgr.set_state(VoiceState.THINKING)

            # 2. Transcribe via Groq Whisper
            transcript = await self.stt.transcribe_wav(audio_bytes, mime_type=mime_type)
            if not transcript or not transcript.strip():
                logger.info("No speech detected in audio turn.")
                await self.state_mgr.set_state(VoiceState.IDLE)
                return {
                    "transcript": "",
                    "reply": "",
                    "state": self.state_mgr.current_state.value
                }

            self.state_mgr.last_transcript = transcript
            logger.info(f"User Spoke: '{transcript}'")

            # 3. Process with Jarvis Brain (Llama 3.3-70B with hardware tools)
            reply = await self.brain.ask(transcript)
            self.state_mgr.last_reply = reply
            logger.info(f"Jarvis Reply: '{reply}'")

            # 4. Synthesize & Speak via Edge-TTS
            await self.tts.speak(reply, voice_state=self.state_mgr)

            # 5. Return to IDLE
            await self.state_mgr.set_state(VoiceState.IDLE)

            return {
                "transcript": transcript,
                "reply": reply,
                "state": self.state_mgr.current_state.value,
                "has_audio": len(self.tts.last_audio_bytes) > 0
            }

    async def process_text_turn(self, text: str) -> Dict[str, Any]:
        """Processes a text prompt directly (from UI prompt box or command)."""
        async with self._turn_lock:
            await self.state_mgr.set_state(VoiceState.THINKING)
            self.state_mgr.last_transcript = text

            reply = await self.brain.ask(text)
            self.state_mgr.last_reply = reply

            await self.tts.speak(reply, voice_state=self.state_mgr)
            await self.state_mgr.set_state(VoiceState.IDLE)

            return {
                "transcript": text,
                "reply": reply,
                "state": self.state_mgr.current_state.value,
                "has_audio": len(self.tts.last_audio_bytes) > 0
            }

    def get_status(self) -> Dict[str, Any]:
        """Returns comprehensive voice system vitals."""
        status = self.state_mgr.to_dict()
        status.update({
            "is_running": self.is_running,
            "mic_capturing": self.audio_capture.is_capturing,
            "mic_available": self.audio_capture.is_available(),
            "device": self.audio_capture.device,
            "voice_name": self.tts.voice,
            "groq_configured": self.stt.is_configured(),
            "has_player": self.tts._player_bin is not None
        })
        return status
