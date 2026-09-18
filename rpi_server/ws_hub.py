import asyncio
import json
import logging
from typing import Optional, Callable, Awaitable

logger = logging.getLogger("WSHub")

class WSHub:
    def __init__(self):
        self.esp32_ws = None
        self.on_button_cb: Optional[Callable[[str], Awaitable[None]]] = None
        self.on_ready_cb: Optional[Callable[[], Awaitable[None]]] = None

    def set_button_callback(self, cb: Callable[[str], Awaitable[None]]):
        self.on_button_cb = cb

    def set_ready_callback(self, cb: Callable[[], Awaitable[None]]):
        self.on_ready_cb = cb

    async def handle_connection(self, websocket):
        self.esp32_ws = websocket
        remote = getattr(websocket, "remote_address", "ESP32")
        logger.info(f"ESP32 connected from {remote}")

        try:
            async for message in websocket:
                if isinstance(message, str):
                    await self._handle_text(message)
                elif isinstance(message, bytes):
                    pass # Binary from ESP32 ignored
        except Exception as e:
            logger.warning(f"ESP32 connection error: {e}")
        finally:
            if self.esp32_ws == websocket:
                self.esp32_ws = None
            logger.info("ESP32 disconnected")

    async def _handle_text(self, data: str):
        try:
            msg = json.loads(data)
            evt = msg.get("evt")
            if evt == "BTN":
                btn = msg.get("btn", "")
                logger.info(f"Button Event: {btn}")
                if self.on_button_cb:
                    await self.on_button_cb(btn)
            elif evt == "READY":
                fw = msg.get("fw", "unknown")
                logger.info(f"ESP32 READY received, firmware v{fw}")
                if self.on_ready_cb:
                    await self.on_ready_cb()
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON received from ESP32: {data}")

    async def send_json(self, obj: dict) -> bool:
        if self.esp32_ws:
            try:
                await self.esp32_ws.send(json.dumps(obj))
                return True
            except Exception as e:
                logger.warning(f"Failed to send JSON: {e}")
                self.esp32_ws = None
        return False

    async def send_binary(self, data: bytes) -> bool:
        if self.esp32_ws:
            try:
                await self.esp32_ws.send(data)
                return True
            except Exception as e:
                logger.warning(f"Failed to send binary frame: {e}")
                self.esp32_ws = None
        return False

    @property
    def connected(self) -> bool:
        return self.esp32_ws is not None
