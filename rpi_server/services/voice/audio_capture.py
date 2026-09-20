import io
import wave
import time
import math
import logging
import asyncio
from typing import Optional, Callable, List

logger = logging.getLogger("AudioCapture")

class AudioCaptureService:
    """Manages audio capture from Bluetooth microphone or system default capture device.
    Uses an in-memory ring buffer with RMS-based Voice Activity Detection (VAD).
    """
    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        rms_threshold: float = 0.018,
        silence_timeout_ms: int = 650,
        device: Optional[str] = "default"
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.rms_threshold = rms_threshold
        self.silence_timeout_ms = silence_timeout_ms
        self.device = device

        self.is_capturing = False
        self.is_speaking = False
        self.last_speech_time = 0.0
        self.speech_start_time = 0.0
        self.current_rms = 0.0

        # In-memory buffer for active speech
        self._speech_buffer = bytearray()
        # Ring buffer for pre-speech lead-in (~300ms)
        self._pre_buffer = bytearray()
        self._pre_buffer_max_bytes = int(sample_rate * 2 * 0.35) # 350ms of 16-bit audio

        # Callbacks
        self.on_speech_started: Optional[Callable[[], Any]] = None
        self.on_speech_ended: Optional[Callable[[bytes], Any]] = None
        self.on_rms_update: Optional[Callable[[float], Any]] = None

        self._stream = None
        self._has_sounddevice = False
        self._init_sounddevice()

    def _init_sounddevice(self):
        try:
            import sounddevice as sd
            import numpy as np
            self._has_sounddevice = True
            logger.info("sounddevice audio stack initialized successfully.")
        except Exception as e:
            logger.warning(f"sounddevice or numpy not available: {e}. Browser push-to-talk will remain functional.")
            self._has_sounddevice = False

    def is_available(self) -> bool:
        return self._has_sounddevice

    @staticmethod
    def pcm_to_wav(pcm_bytes: bytes, sample_rate: int = 16000, channels: int = 1) -> bytes:
        """Encodes raw 16-bit PCM bytes into an in-memory WAV container."""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(2) # 16-bit
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_bytes)
        return buf.getvalue()

    def _calculate_rms(self, pcm_chunk: bytes) -> float:
        """Fast RMS calculation of 16-bit PCM audio chunk."""
        if not pcm_chunk:
            return 0.0
        count = len(pcm_chunk) // 2
        if count == 0:
            return 0.0
        try:
            import struct
            shorts = struct.unpack(f"<{count}h", pcm_chunk)
            sum_squares = sum(s * s for s in shorts)
            mean_square = sum_squares / count
            return math.sqrt(mean_square) / 32768.0
        except Exception:
            return 0.0

    def process_incoming_chunk(self, chunk: bytes, loop=None):
        """Called for every incoming 16-bit mono PCM chunk (e.g. from sounddevice or WebSocket)."""
        rms = self._calculate_rms(chunk)
        self.current_rms = rms

        if self.on_rms_update:
            try:
                self.on_rms_update(rms)
            except Exception:
                pass

        now = time.time()

        if rms >= self.rms_threshold:
            # SPEECH DETECTED
            self.last_speech_time = now
            if not self.is_speaking:
                self.is_speaking = True
                self.speech_start_time = now
                logger.info("Voice Activity Detected (Speech started)")
                self._speech_buffer.clear()
                # Include pre-speech buffer so first phoneme isn't clipped
                self._speech_buffer.extend(self._pre_buffer)

                if self.on_speech_started:
                    if loop:
                        asyncio.run_coroutine_threadsafe(self._async_call(self.on_speech_started), loop)
                    else:
                        res = self.on_speech_started()
                        if asyncio.iscoroutine(res):
                            asyncio.create_task(res)

            self._speech_buffer.extend(chunk)

        elif self.is_speaking:
            # USER IS SPEAKING, BUT THIS CHUNK WAS QUIET
            self._speech_buffer.extend(chunk)
            silence_ms = (now - self.last_speech_time) * 1000.0

            if silence_ms >= self.silence_timeout_ms:
                # SPEECH FINISHED!
                total_duration = now - self.speech_start_time
                self.is_speaking = False
                logger.info(f"Voice Activity Ended (Speech duration: {total_duration:.2f}s, size: {len(self._speech_buffer)} bytes)")

                # Require at least 0.5s of speech to avoid false trigger clicks
                if total_duration >= 0.45 and len(self._speech_buffer) >= int(self.sample_rate * 2 * 0.45):
                    pcm_out = bytes(self._speech_buffer)
                    if self.on_speech_ended:
                        if loop:
                            asyncio.run_coroutine_threadsafe(self._async_call(self.on_speech_ended, pcm_out), loop)
                        else:
                            res = self.on_speech_ended(pcm_out)
                            if asyncio.iscoroutine(res):
                                asyncio.create_task(res)

                self._speech_buffer.clear()

        else:
            # IDLE SILENCE - maintain circular pre-speech buffer
            self._pre_buffer.extend(chunk)
            if len(self._pre_buffer) > self._pre_buffer_max_bytes:
                del self._pre_buffer[:len(self._pre_buffer) - self._pre_buffer_max_bytes]

    async def _async_call(self, fn, *args):
        try:
            res = fn(*args)
            if asyncio.iscoroutine(res):
                await res
        except Exception as e:
            logger.error(f"Error in async audio capture callback: {e}")

    def start_background_stream(self, loop=None):
        """Starts non-blocking capture stream via sounddevice."""
        if not self._has_sounddevice:
            logger.warning("sounddevice not available, cannot start background mic stream.")
            return False

        try:
            import sounddevice as sd
            def callback(indata, frames, time_info, status):
                if status:
                    logger.debug(f"sounddevice status: {status}")
                chunk = indata.tobytes()
                self.process_incoming_chunk(chunk, loop=loop)

            # Block size 40ms = 640 frames at 16kHz
            block_size = int(self.sample_rate * 0.04)
            dev = None if self.device == "default" else self.device

            try:
                self._stream = sd.RawInputStream(
                    samplerate=self.sample_rate,
                    blocksize=block_size,
                    device=dev,
                    channels=self.channels,
                    dtype='int16',
                    callback=callback
                )
                self._stream.start()
            except Exception as e_rate:
                logger.warning(f"Failed to open audio stream with {self.sample_rate}Hz: {e_rate}. Trying device default samplerate...")
                try:
                    dev_info = sd.query_devices(dev, 'input')
                    native_rate = int(dev_info.get('default_samplerate', 16000))
                    self.sample_rate = native_rate
                    block_size = int(self.sample_rate * 0.04)
                    self._stream = sd.RawInputStream(
                        samplerate=self.sample_rate,
                        blocksize=block_size,
                        device=dev,
                        channels=self.channels,
                        dtype='int16',
                        callback=callback
                    )
                    self._stream.start()
                except Exception as e_retry:
                    logger.error(f"Fallback audio stream also failed: {e_retry}")
                    self.is_capturing = False
                    return False

            self.is_capturing = True
            logger.info(f"Microphone stream started on device '{self.device}' ({self.sample_rate}Hz mono).")
            return True
        except Exception as e:
            logger.warning(f"Could not open audio capture device: {e}")
            self.is_capturing = False
            return False

    def list_devices(self) -> List[dict]:
        """Lists all input audio devices detected by sounddevice."""
        if not self._has_sounddevice:
            return []
        try:
            import sounddevice as sd
            devs = sd.query_devices()
            results = []
            default_in = sd.default.device[0] if sd.default.device else -1
            for i, d in enumerate(devs):
                if d.get("max_input_channels", 0) > 0:
                    results.append({
                        "index": i,
                        "name": d.get("name", f"Device {i}"),
                        "channels": d.get("max_input_channels", 1),
                        "default_samplerate": int(d.get("default_samplerate", 16000)),
                        "is_default": (i == default_in)
                    })
            return results
        except Exception as e:
            logger.warning(f"Error querying input devices: {e}")
            return []

    def set_device(self, dev_id_or_name, loop=None) -> bool:
        """Changes the active audio capture device."""
        try:
            if isinstance(dev_id_or_name, str) and dev_id_or_name.isdigit():
                self.device = int(dev_id_or_name)
            elif dev_id_or_name == "default":
                self.device = "default"
            else:
                self.device = dev_id_or_name

            if self.is_capturing:
                self.stop_stream()
                return self.start_background_stream(loop=loop)
            return True
        except Exception as e:
            logger.error(f"Error switching audio device: {e}")
            return False

    def stop_stream(self):
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self.is_capturing = False
        logger.info("Audio capture stream stopped.")
