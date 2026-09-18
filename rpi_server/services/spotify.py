import io
import time
import base64
import logging
import httpx
from PIL import Image
from config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_REFRESH_TOKEN

logger = logging.getLogger("SpotifyService")

class SpotifyService:
    def __init__(self):
        self.access_token = None
        self.token_expiry = 0
        self.last_track_id = None
        self.last_image_url = None
        self.is_playing = False

    async def get_access_token(self) -> str:
        if self.access_token and time.time() < self.token_expiry - 60:
            return self.access_token

        if not (SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET and SPOTIFY_REFRESH_TOKEN):
            return None

        url = "https://accounts.spotify.com/api/token"
        auth_header = base64.b64encode(f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()).decode()
        headers = {
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        data = {
            "grant_type": "refresh_token",
            "refresh_token": SPOTIFY_REFRESH_TOKEN
        }

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                res = await client.post(url, headers=headers, data=data)
                if res.status_code == 200:
                    payload = res.json()
                    self.access_token = payload.get("access_token")
                    expires_in = payload.get("expires_in", 3600)
                    self.token_expiry = time.time() + expires_in
                    logger.info("Spotify access token refreshed")
                    return self.access_token
                else:
                    logger.error(f"Spotify token refresh failed: {res.status_code} {res.text}")
        except Exception as e:
            logger.error(f"Error requesting Spotify token: {e}")
        return None

    async def get_now_playing(self) -> dict:
        token = await self.get_access_token()
        if not token:
            return None

        url = "https://api.spotify.com/v1/me/player/currently-playing"
        headers = {"Authorization": f"Bearer {token}"}

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.get(url, headers=headers)
                if res.status_code == 204 or res.status_code > 400:
                    return {"playing": False}
                if res.status_code == 200:
                    data = res.json()
                    if not data or not data.get("item"):
                        return {"playing": False}

                    item = data["item"]
                    artists = ", ".join([a["name"] for a in item.get("artists", [])])
                    img_url = None
                    images = item.get("album", {}).get("images", [])
                    if images:
                        # Grab medium size (~300px) or first image
                        img_url = images[1]["url"] if len(images) > 1 else images[0]["url"]

                    return {
                        "playing": data.get("is_playing", False),
                        "id": item.get("id"),
                        "title": item.get("name", "Unknown"),
                        "artist": artists,
                        "progress_ms": data.get("progress_ms", 0),
                        "duration_ms": item.get("duration_ms", 0),
                        "image_url": img_url
                    }
        except Exception as e:
            logger.warning(f"Error fetching Spotify player: {e}")
        return None

    async def fetch_and_convert_art(self, url: str) -> bytes:
        """Downloads album art, resizes to 100x100 and converts directly to raw RGB565 binary."""
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return None

                img = Image.open(io.BytesIO(resp.content))
                img = img.resize((100, 100), Image.LANCZOS).convert("RGB")

                # Convert to raw 16-bit RGB565 (big-endian)
                buf = bytearray(100 * 100 * 2)
                for i, (r, g, b) in enumerate(img.getdata()):
                    rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
                    buf[i * 2]     = (rgb565 >> 8) & 0xFF
                    buf[i * 2 + 1] = rgb565 & 0xFF

                # Prepend magic header: 0xAA 0xBB width height
                header = bytes([0xAA, 0xBB, 100, 100])
                return header + bytes(buf)
        except Exception as e:
            logger.error(f"Error converting album art: {e}")
            return None

    async def poll(self, hub, emotion_engine=None):
        if not hub.connected:
            return

        np = await self.get_now_playing()
        if not np:
            return

        playing = np.get("playing", False)
        track_id = np.get("id")
        img_url = np.get("image_url")

        track_changed = (track_id != self.last_track_id)
        playing_changed = (playing != self.is_playing)

        self.is_playing = playing
        self.last_track_id = track_id

        # Send updated JSON track info to ESP32
        await hub.send_json({
            "cmd": "SPOTIFY",
            "title": np.get("title", ""),
            "artist": np.get("artist", ""),
            "progress_ms": np.get("progress_ms", 0),
            "duration_ms": np.get("duration_ms", 0),
            "playing": playing
        })

        # If track changed, fetch and stream the 100x100 RGB565 bitmap to ESP32
        if track_changed and img_url and img_url != self.last_image_url:
            self.last_image_url = img_url
            art_frame = await self.fetch_and_convert_art(img_url)
            if art_frame:
                await hub.send_binary(art_frame)
                logger.info("Streamed 100x100 RGB565 album art to ESP32")

        # Update Emotion on state change
        if emotion_engine and (track_changed or playing_changed):
            if playing:
                await emotion_engine.on_spotify_playing(hub)
            else:
                await emotion_engine.on_spotify_paused(hub)

    async def skip_next(self, hub):
        token = await self.get_access_token()
        if not token: return
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                await client.post("https://api.spotify.com/v1/me/player/next", headers={"Authorization": f"Bearer {token}"})
                logger.info("Spotify skip next")
        except Exception as e:
            logger.error(f"Error skipping track: {e}")

    async def skip_prev(self, hub):
        token = await self.get_access_token()
        if not token: return
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                await client.post("https://api.spotify.com/v1/me/player/previous", headers={"Authorization": f"Bearer {token}"})
                logger.info("Spotify skip previous")
        except Exception as e:
            logger.error(f"Error skipping track: {e}")

    async def toggle_play(self, hub):
        token = await self.get_access_token()
        if not token: return
        endpoint = "pause" if self.is_playing else "play"
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                await client.put(f"https://api.spotify.com/v1/me/player/{endpoint}", headers={"Authorization": f"Bearer {token}"})
                logger.info(f"Spotify {endpoint}")
        except Exception as e:
            logger.error(f"Error toggling playback: {e}")
