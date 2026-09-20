import asyncio
import logging
import urllib.parse
from io import BytesIO
from typing import Optional, Dict, Any
import httpx
from PIL import Image

logger = logging.getLogger("IOSCompanion")

class IOSCompanionService:
    def __init__(self):
        self.connected_device_name = ""
        self.is_connected = False
        self.current_title = ""
        self.current_artist = ""
        self.current_album = ""
        self.is_playing = False
        self.progress_ms = 0
        self.duration_ms = 0
        self.last_art_url = ""
        self._dbus_available = False
        self._init_dbus()

    def _init_dbus(self):
        """Attempts to initialize Linux BlueZ D-Bus connection."""
        try:
            import dbus
            self.bus = dbus.SystemBus()
            self._dbus_available = True
            logger.info("Linux BlueZ D-Bus initialized successfully.")
        except Exception as e:
            logger.warning(f"BlueZ D-Bus not available or not running Linux: {e}")
            self._dbus_available = False

    def _rgb888_to_rgb565(self, r: int, g: int, b: int) -> int:
        return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)

    async def fetch_itunes_album_art(self, title: str, artist: str) -> Optional[bytes]:
        """Fetches official high-res album artwork via iTunes Search API and converts to RGB565."""
        try:
            query = f"{title} {artist}"
            encoded_query = urllib.parse.quote(query)
            url = f"https://itunes.apple.com/search?term={encoded_query}&entity=song&limit=1"

            async with httpx.AsyncClient(timeout=4.0) as client:
                res = await client.get(url)
                if res.status_code != 200:
                    return None

                data = res.json()
                if not data.get("results"):
                    return None

                art_url = data["results"][0].get("artworkUrl100", "")
                if not art_url:
                    return None

                # Upgrade to 600x600 resolution
                art_url_high = art_url.replace("100x100bb.jpg", "600x600bb.jpg")
                img_res = await client.get(art_url_high)
                if img_res.status_code != 200:
                    img_res = await client.get(art_url)

                img = Image.open(BytesIO(img_res.content)).convert("RGB")
                img = img.resize((100, 100), Image.Resampling.LANCZOS)

                # Construct 20004 byte binary buffer (0xAA 0xBB width height + RGB565)
                buf = bytearray(20004)
                buf[0] = 0xAA
                buf[1] = 0xBB
                buf[2] = 100
                buf[3] = 100

                idx = 4
                for y in range(100):
                    for x in range(100):
                        r, g, b = img.getpixel((x, y))
                        rgb565 = self._rgb888_to_rgb565(r, g, b)
                        buf[idx] = (rgb565 >> 8) & 0xFF
                        buf[idx + 1] = rgb565 & 0xFF
                        idx += 2

                return bytes(buf)
        except Exception as e:
            logger.warning(f"Error fetching album art from iTunes for {title}: {e}")
            return None

    async def _run_busctl(self, args: list) -> str:
        """Executes a busctl system call."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "busctl", "--system", *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=3.0)
            return stdout.decode("utf-8", errors="ignore").strip()
        except Exception as e:
            return ""

    async def _find_player_path(self) -> Optional[str]:
        """Finds any active BlueZ MediaPlayer1 object path (e.g. /org/bluez/hci0/dev_.../player0)."""
        tree_out = await self._run_busctl(["tree", "org.bluez"])
        for line in tree_out.splitlines():
            if "/player" in line:
                for part in line.strip().split():
                    if part.startswith("/org/bluez") and "/player" in part:
                        return part
        return None

    async def next_track(self):
        """Sends Next track command to phone via BlueZ AVRCP."""
        player_path = await self._find_player_path()
        if player_path:
            await self._run_busctl(["call", "org.bluez", player_path, "org.bluez.MediaPlayer1", "Next"])
            logger.info(f"Sent Next command to {player_path}")

    async def prev_track(self):
        """Sends Previous track command to phone via BlueZ AVRCP."""
        player_path = await self._find_player_path()
        if player_path:
            await self._run_busctl(["call", "org.bluez", player_path, "org.bluez.MediaPlayer1", "Previous"])
            logger.info(f"Sent Previous command to {player_path}")

    async def toggle_play(self):
        """Toggles Play/Pause on phone via BlueZ AVRCP."""
        player_path = await self._find_player_path()
        if player_path:
            cmd = "Pause" if self.is_playing else "Play"
            await self._run_busctl(["call", "org.bluez", player_path, "org.bluez.MediaPlayer1", cmd])
            logger.info(f"Sent {cmd} command to {player_path}")

    async def _poll_python_dbus(self, hub):
        """Internal poller using python-dbus if installed."""
        import dbus
        manager = dbus.Interface(
            self.bus.get_object("org.bluez", "/"),
            "org.freedesktop.DBus.ObjectManager"
        )
        objects = manager.GetManagedObjects()

        player_found = False
        for path, interfaces in objects.items():
            if "org.bluez.MediaPlayer1" in interfaces:
                player_found = True
                player = dbus.Interface(
                    self.bus.get_object("org.bluez", path),
                    "org.freedesktop.DBus.Properties"
                )
                status = str(player.Get("org.bluez.MediaPlayer1", "Status"))
                track = player.Get("org.bluez.MediaPlayer1", "Track")
                position = int(player.Get("org.bluez.MediaPlayer1", "Position")) if "Position" in interfaces["org.bluez.MediaPlayer1"] else 0

                title = str(track.get("Title", ""))
                artist = str(track.get("Artist", ""))
                album = str(track.get("Album", ""))
                duration = int(track.get("Duration", 0))

                is_playing = (status.lower() == "playing")
                track_changed = (title != self.current_title or artist != self.current_artist)
                self.current_title = title
                self.current_artist = artist
                self.current_album = album
                self.is_playing = is_playing
                self.duration_ms = duration
                self.progress_ms = position
                self.is_connected = True

                if title:
                    await hub.send_json({
                        "cmd": "SPOTIFY",
                        "title": title[:32],
                        "artist": artist[:32],
                        "progress_ms": position,
                        "duration_ms": duration,
                        "playing": is_playing,
                        "source": "ios"
                    })

                if track_changed and title:
                    logger.info(f"iOS Track Changed: {title} by {artist}")
                    art_bytes = await self.fetch_itunes_album_art(title, artist)
                    if art_bytes:
                        await hub.send_binary(art_bytes)
                break

        if not player_found:
            self.is_connected = False

    async def _poll_busctl(self, hub):
        """Fallback poller using systemd busctl CLI (works in any venv without python-dbus)."""
        player_path = await self._find_player_path()
        if not player_path:
            self.is_connected = False
            return

        status_out = await self._run_busctl(["get-property", "org.bluez", player_path, "org.bluez.MediaPlayer1", "Status"])
        is_playing = "playing" in status_out.lower()

        pos_out = await self._run_busctl(["get-property", "org.bluez", player_path, "org.bluez.MediaPlayer1", "Position"])
        position_ms = 0
        try:
            parts = pos_out.split()
            if len(parts) >= 2:
                position_ms = int(parts[1])
        except Exception:
            pass

        track_out = await self._run_busctl(["get-property", "org.bluez", player_path, "org.bluez.MediaPlayer1", "Track"])
        import re
        title_m = re.search(r'"Title"\s+s\s+"([^"]+)"', track_out)
        artist_m = re.search(r'"Artist"\s+s\s+"([^"]+)"', track_out)
        album_m = re.search(r'"Album"\s+s\s+"([^"]+)"', track_out)
        dur_m = re.search(r'"Duration"\s+u\s+(\d+)', track_out)

        title = title_m.group(1) if title_m else ""
        artist = artist_m.group(1) if artist_m else ""
        album = album_m.group(1) if album_m else ""
        duration_ms = int(dur_m.group(1)) if dur_m else 0

        track_changed = (title != self.current_title or artist != self.current_artist)
        self.current_title = title
        self.current_artist = artist
        self.current_album = album
        self.is_playing = is_playing
        self.duration_ms = duration_ms
        self.progress_ms = position_ms
        self.is_connected = True

        if title:
            await hub.send_json({
                "cmd": "SPOTIFY",
                "title": title[:32],
                "artist": artist[:32],
                "progress_ms": position_ms,
                "duration_ms": duration_ms,
                "playing": is_playing,
                "source": "ios"
            })

        if track_changed and title:
            logger.info(f"iOS Track Changed (via busctl): {title} by {artist}")
            art_bytes = await self.fetch_itunes_album_art(title, artist)
            if art_bytes:
                await hub.send_binary(art_bytes)

    async def poll_bluetooth_media(self, hub, anim_engine=None):
        """Polls BlueZ org.bluez.MediaPlayer1 via Python dbus or busctl CLI fallback."""
        if self._dbus_available:
            try:
                await self._poll_python_dbus(hub)
                return
            except Exception:
                pass
        # Fallback to busctl CLI
        try:
            await self._poll_busctl(hub)
        except Exception as e:
            logger.debug(f"busctl poll error: {e}")
            self.is_connected = False

    async def push_notification(self, app_name: str, title: str, message: str, hub):
        """Pushes an incoming phone notification with a haptic alert and display card."""
        logger.info(f"Notification from [{app_name}] {title}: {message}")
        # 1. Haptic buzz
        await hub.send_json({"cmd": "HAPTIC", "ms": 90})

        # 2. Display notification on screen
        await hub.send_json({
            "cmd": "NOTIF",
            "app": app_name[:16],
            "title": title[:24],
            "body": message[:60]
        })
