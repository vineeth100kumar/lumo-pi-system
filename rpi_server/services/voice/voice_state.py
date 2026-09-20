import logging
import asyncio
from enum import Enum
from typing import Optional, Callable, List, Dict, Any

logger = logging.getLogger("VoiceState")

class VoiceState(str, Enum):
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"
    ERROR = "ERROR"

class VoiceStateManager:
    """Coordinates state transitions between audio capture, STT, LLM, and TTS.
    Broadcasts state updates to the ESP32 and Web Dashboard.
    """
    def __init__(self, hub=None, anim_engine=None):
        self.hub = hub
        self.anim_engine = anim_engine
        self.current_state: VoiceState = VoiceState.IDLE
        self.current_subtitle: str = ""
        self.current_volume: float = 0.0
        self.last_transcript: str = ""
        self.last_reply: str = ""
        self._listeners: List[Callable[[VoiceState, str], Any]] = []

    def add_listener(self, callback: Callable[[VoiceState, str], Any]):
        self._listeners.append(callback)

    async def set_state(self, state: VoiceState, subtitle: str = "", volume: float = 0.0):
        if self.current_state == state and self.current_subtitle == subtitle:
            return

        old_state = self.current_state
        self.current_state = state
        self.current_subtitle = subtitle
        self.current_volume = volume

        logger.info(f"Voice State: {old_state} -> {state} | '{subtitle}'")

        # 1. Notify local in-process listeners
        for listener in self._listeners:
            try:
                res = listener(state, subtitle)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as e:
                logger.debug(f"Error in voice state listener: {e}")

        # 2. Broadcast to physical ESP32 via WebSocket
        if self.hub and self.hub.connected:
            try:
                payload = {
                    "cmd": "VOICE_STATE",
                    "state": state.value,
                    "subtitle": subtitle[:48] if subtitle else "",
                    "volume": round(volume, 2)
                }
                await self.hub.send_json(payload)

                # Visual & Haptic reaction helpers
                if state == VoiceState.LISTENING and old_state != VoiceState.LISTENING:
                    # Snappy 35ms haptic confirmation click
                    await self.hub.send_json({"cmd": "HAPTIC", "ms": 35})
                    # Cyan breathing light
                    await self.hub.send_json({"cmd": "LIGHTS", "mode": "BREATHE", "brightness": 60, "hue": 180})
                elif state == VoiceState.THINKING:
                    # Amber rotate / think light
                    await self.hub.send_json({"cmd": "LIGHTS", "mode": "COLOR", "brightness": 70, "hue": 35})
                elif state == VoiceState.IDLE and old_state != VoiceState.IDLE:
                    # Restore gentle ambient warm lighting
                    await self.hub.send_json({"cmd": "LIGHTS", "mode": "WARM", "brightness": 40, "hue": 0})
            except Exception as e:
                logger.warning(f"Failed to broadcast voice state to ESP32: {e}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.current_state.value,
            "subtitle": self.current_subtitle,
            "volume": self.current_volume,
            "last_transcript": self.last_transcript,
            "last_reply": self.last_reply
        }
