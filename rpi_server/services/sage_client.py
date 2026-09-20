"""
Lumo's one connection to Sage.

Lumo used to keep its own tasks in tasks.json and its own alarms in
alarms.json, which meant the desk companion and the phone app each believed a
different list. They share one store now: the SQLite database behind Sage.

Lumo does not open that file. Sage's rules live in its backend rather than in
its schema -- recurrence, which reminders have already been sent, the parser
that turns "leave office by 6.30" into a scheduled item -- and a second writer
would have to reimplement all of it, while the phone app, which refreshes from
Sage's websocket and not from the file, would never hear about the change. So
Lumo asks Sage instead, over the loopback address, and Sage stays the only
thing that touches the database. Neither project imports a line of the other.
"""

import asyncio
import datetime
import json
import logging
import os
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import httpx
import websockets

from config import (
    SAGE_API_KEY,
    SAGE_API_URL,
    SAGE_ENV_FILE,
    SAGE_REQUEST_TIMEOUT,
    SAGE_SECRET_FILE,
)

logger = logging.getLogger("SageClient")

# Sage compares reminder times against a naive `datetime.now()` in the Pi's own
# timezone, so every timestamp Lumo sends it has to be naive local time too. An
# aware IST string would be read as a different moment and the alarm would ring
# five and a half hours out.
def now_local() -> datetime.datetime:
    return datetime.datetime.now()


def _key_from_env_file(path: str) -> str:
    """Read API_SECRET out of Sage's environment file, if it is readable."""
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            if name.strip() == "API_SECRET":
                return value.strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def resolve_api_key() -> str:
    """
    Find Sage's key without ever storing a second copy of it.

    The key is written in exactly one place, /etc/sage/sage.env, which is
    root-owned and unreadable by the pi user. Lumo's systemd unit therefore
    carries the same EnvironmentFile line Sage's does: systemd reads the file
    as root and hands the value down. The rest is for running main.py by hand.
    """
    for candidate in (SAGE_API_KEY, os.environ.get("API_SECRET", "")):
        if candidate and candidate.strip():
            return candidate.strip()

    from_file = _key_from_env_file(SAGE_ENV_FILE)
    if from_file:
        return from_file

    # Sage writes a random key into its data directory when none was
    # configured, which is the likeliest case on a Pi where API_SECRET was
    # never set. Where that directory is depends on the user and on what the
    # checkout was called, so look in the usual places rather than one.
    home = Path.home()
    candidates = [Path(SAGE_SECRET_FILE)] + [
        home / name / "data" / "api_secret.txt"
        for name in ("sage-os", "TASK_MANAGER", "task_manager", "sage")
    ]
    for candidate in candidates:
        try:
            key = candidate.read_text(encoding="utf-8").strip()
        except Exception:
            continue
        if key:
            logger.info(f"Using the Sage key from {candidate}")
            return key
    return ""


class SageClient:
    """Thin async wrapper over Sage's REST API and live websocket."""

    def __init__(self, base_url: str = SAGE_API_URL):
        self.base_url = base_url.rstrip("/")
        self.api_key = resolve_api_key()
        self.online = False
        self.last_error = "" if self.api_key else "No Sage API key found"
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    @property
    def ws_url(self) -> str:
        scheme = "wss" if self.base_url.startswith("https") else "ws"
        host = self.base_url.split("://", 1)[-1]
        return f"{scheme}://{host}/ws"

    def status(self) -> dict:
        return {
            "configured": self.is_configured,
            "online": self.online,
            "url": self.base_url,
            "last_error": self.last_error,
        }

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=SAGE_REQUEST_TIMEOUT,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
        return self._client

    async def request(self, method: str, path: str, **kwargs) -> Any:
        """
        One call to Sage. Returns None rather than raising when Sage is down,
        so a restarting backend leaves the desk companion showing its last
        known list instead of an error.
        """
        if not self.is_configured:
            self.online = False
            self.last_error = "No Sage API key found"
            return None
        try:
            client = await self._get_client()
            response = await client.request(method, path, **kwargs)
            response.raise_for_status()
            self.online = True
            self.last_error = ""
            if response.status_code == 204 or not response.content:
                return {}
            return response.json()
        except httpx.HTTPStatusError as exc:
            self.online = True
            self.last_error = f"{exc.response.status_code} from Sage on {path}"
            if exc.response.status_code == 401:
                self.last_error = "Sage rejected Lumo's API key"
            logger.error(self.last_error)
            return None
        except Exception as exc:
            self.online = False
            self.last_error = f"Sage unreachable: {exc}"
            logger.warning(self.last_error)
            return None

    # ---------------- Work items ----------------

    async def list_items(self, **params) -> list[dict]:
        data = await self.request("GET", "/api/v1/items", params=params)
        return data if isinstance(data, list) else []

    async def create_item(self, payload: dict) -> Optional[dict]:
        return await self.request("POST", "/api/v1/items", json=payload)

    async def update_item(self, item_id: str, payload: dict) -> Optional[dict]:
        return await self.request("PATCH", f"/api/v1/items/{item_id}", json=payload)

    async def delete_item(self, item_id: str) -> bool:
        return await self.request("DELETE", f"/api/v1/items/{item_id}") is not None

    async def capture(self, text: str) -> Optional[dict]:
        """
        Hand a line of ordinary speech to Sage's capture engine, so "call mum
        at 6" spoken at Lumo becomes the same scheduled item it would if typed
        into the app, rather than a bare string on a display.
        """
        return await self.request(
            "POST", "/api/v1/ai/capture", json={"text": text, "commit": True}
        )

    # ---------------- Live events ----------------

    async def listen(self, handler: Callable[[dict], Awaitable[None]]) -> None:
        """
        Follow Sage's event stream forever, reconnecting when it drops.

        This is what puts Sage's reminders on the desk clock: every item
        created, updated or fallen due arrives here within the second, so Lumo
        never polls for them.
        """
        backoff = 2
        while True:
            if not self.is_configured:
                await asyncio.sleep(30)
                continue
            try:
                async with websockets.connect(self.ws_url) as socket:
                    # The socket is accepted before it is trusted: the first
                    # frame has to be the key, or Sage closes the connection.
                    await socket.send(json.dumps({"type": "auth", "token": self.api_key}))
                    logger.info(f"Connected to Sage event stream at {self.ws_url}")
                    backoff = 2
                    self.online = True
                    async for raw in socket:
                        try:
                            event = json.loads(raw)
                        except (ValueError, TypeError):
                            continue
                        if not isinstance(event, dict) or not event.get("type"):
                            continue
                        try:
                            await handler(event)
                        except Exception as exc:
                            logger.error(f"Error handling Sage event: {exc}")
            except Exception as exc:
                self.online = False
                logger.warning(f"Sage event stream lost ({exc}); retrying in {backoff}s")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
