import asyncio
import hashlib
import io
import json
import logging
import os
import time
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any
from PIL import Image, ImageOps, ImageEnhance

logger = logging.getLogger("MemoriesService")

class MemoriesService:
    def __init__(self, base_dir: Optional[str] = None):
        if not base_dir:
            server_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.base_dir = os.path.join(server_dir, "static", "memories")
        else:
            self.base_dir = os.path.abspath(base_dir)

        self.inbox_dir = os.path.join(self.base_dir, "inbox")
        self.library_dir = os.path.join(self.base_dir, "library")
        self.thumbs_dir = os.path.join(self.base_dir, "thumbs")
        self.index_file = os.path.join(self.base_dir, "index.json")

        for d in (self.inbox_dir, self.library_dir, self.thumbs_dir):
            os.makedirs(d, exist_ok=True)

        self.photos: List[Dict[str, Any]] = []
        self.current_index = 0
        self.auto_rotate = True
        self.interval_sec = 20
        self.max_photos = 50
        self.nightly_quota = 0  # 0 = unlimited uploads per night
        self.nightly_uploads: Dict[str, int] = {}
        self.replace_duplicates = True
        self.swap_bytes = True
        self.bgr_mode = False

        self._load_index()

    def _load_index(self):
        if os.path.exists(self.index_file):
            try:
                with open(self.index_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.photos = data.get("photos", [])
                    self.auto_rotate = data.get("auto_rotate", True)
                    self.interval_sec = data.get("interval_sec", 20)
                    self.max_photos = data.get("max_photos", 50)
                    if self.max_photos < 50:
                        self.max_photos = 50
                    self.nightly_quota = data.get("nightly_quota", 0)
                    if self.nightly_quota == 5:
                        self.nightly_quota = 0  # upgrade from previous default to unlimited
                    self.replace_duplicates = data.get("replace_duplicates", True)

                    # Backfill fingerprint hashes for existing library if missing
                    for p in self.photos:
                        if not p.get("pixel_hash") or not p.get("dhash"):
                            lib_p = os.path.join(self.library_dir, p.get("filename", ""))
                            if os.path.exists(lib_p):
                                try:
                                    with Image.open(lib_p) as ex_img:
                                        p["pixel_hash"] = hashlib.md5(ex_img.tobytes()).hexdigest()
                                        p["dhash"] = self._calc_dhash(ex_img)
                                except Exception:
                                    pass

                    # Enforce max quota on existing library
                    while len(self.photos) > self.max_photos:
                        old = self.photos.pop()
                        self._delete_disk_files(old)

                    logger.info(f"Loaded {len(self.photos)} memories from index (Quota: {self.max_photos} max FIFO rolling buffer).")
            except Exception as e:
                logger.warning(f"Could not load memories index: {e}")
                self.photos = []

    def _save_index(self):
        try:
            with open(self.index_file, "w", encoding="utf-8") as f:
                json.dump({
                    "photos": self.photos,
                    "auto_rotate": self.auto_rotate,
                    "interval_sec": self.interval_sec,
                    "max_photos": self.max_photos,
                    "nightly_quota": self.nightly_quota,
                    "nightly_uploads": self.nightly_uploads,
                    "replace_duplicates": self.replace_duplicates,
                    "updated_at": datetime.now().isoformat()
                }, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save memories index: {e}")

    @staticmethod
    def _calc_dhash(img: Image.Image) -> str:
        """Computes a 64-bit difference hash (dhash) for perceptual duplicate detection."""
        try:
            small = img.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
            pixels = list(small.getdata())
            diff = []
            for row in range(8):
                row_offset = row * 9
                for col in range(8):
                    diff.append(pixels[row_offset + col] > pixels[row_offset + col + 1])
            decimal_val = 0
            for bit in diff:
                decimal_val = (decimal_val << 1) | int(bit)
            return f"{decimal_val:016x}"
        except Exception:
            return ""

    @staticmethod
    def _hamming_distance(s1: str, s2: str) -> int:
        """Returns bit difference between two 64-bit hex hash strings."""
        if not s1 or not s2 or len(s1) != len(s2):
            return 999
        try:
            return bin(int(s1, 16) ^ int(s2, 16)).count("1")
        except ValueError:
            return 999

    def _get_logical_night_key(self) -> str:
        """Returns the logical night date key (shifts midnight to 6:00 AM).
        11:00 PM on Sept 21 and 2:00 AM on Sept 22 belong to the same night bucket.
        """
        from datetime import timedelta
        now = datetime.now()
        logical_date = now - timedelta(hours=6)
        return logical_date.strftime("%Y-%m-%d")

    def get_nightly_upload_count(self) -> int:
        key = self._get_logical_night_key()
        return self.nightly_uploads.get(key, 0)

    def get_nightly_remaining(self) -> int:
        if self.nightly_quota <= 0:
            return 999999
        return max(0, self.nightly_quota - self.get_nightly_upload_count())

    def record_nightly_upload(self, count: int = 1):
        if count <= 0:
            return
        key = self._get_logical_night_key()
        self.nightly_uploads[key] = self.nightly_uploads.get(key, 0) + count
        # Retain last 14 days of history
        if len(self.nightly_uploads) > 14:
            sorted_keys = sorted(self.nightly_uploads.keys())
            for old_k in sorted_keys[:-14]:
                del self.nightly_uploads[old_k]
        self._save_index()

    def reset_tonight_uploads(self):
        key = self._get_logical_night_key()
        if key in self.nightly_uploads:
            del self.nightly_uploads[key]
            self._save_index()

    def set_quotas(self, max_photos: Optional[int] = None, nightly_quota: Optional[int] = None):
        if max_photos is not None:
            self.max_photos = max(1, max_photos)
            while len(self.photos) > self.max_photos:
                old = self.photos.pop()
                self._delete_disk_files(old)
        if nightly_quota is not None:
            self.nightly_quota = max(0, nightly_quota)
        self._save_index()

    def _rgb888_to_rgb565(self, r: int, g: int, b: int) -> int:
        if self.bgr_mode:
            r, b = b, r
        return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)

    def _extract_caption_date(self, img: Image.Image) -> str:
        """Extracts date taken from EXIF if available, else current date."""
        try:
            exif = img.getexif()
            if exif:
                # 36867: DateTimeOriginal, 306: DateTime
                dt_str = exif.get(36867) or exif.get(306)
                if dt_str:
                    # format usually "YYYY:MM:DD HH:MM:SS"
                    parts = dt_str.split(" ")[0].split(":")
                    if len(parts) == 3:
                        dt = datetime(int(parts[0]), int(parts[1]), int(parts[2]))
                        return dt.strftime("%d %b %Y")
        except Exception:
            pass
        return datetime.now().strftime("%d %b %Y")

    async def ingest_from_path(self, path: str, hub=None) -> Optional[Dict[str, Any]]:
        """Called by the watchdog handler when a file arrives in the inbox."""
        # Short settle delay to avoid reading partially-written files
        await asyncio.sleep(0.6)
        if not os.path.exists(path):
            return None

        filename = os.path.basename(path)
        logger.info(f"Ingesting memory from inbox: {filename}")

        try:
            with open(path, "rb") as f:
                raw = f.read()

            os.remove(path)
            return await self.ingest_bytes(raw, hub=hub, source="obex", filename=filename)
        except Exception as e:
            logger.error(f"Error processing inbox file {path}: {e}")
            if os.path.exists(path):
                try: os.remove(path)
                except Exception: pass
            return None

    async def ingest_bytes(self, raw: bytes, hub=None, source: str = "upload", filename: str = "", caption: Optional[str] = None, notify: bool = True) -> Optional[Dict[str, Any]]:
        """Shared processing core for Bluetooth OBEX, Web Upload, and iOS Shortcuts."""
        if not raw:
            return None

        try:
            img = Image.open(io.BytesIO(raw))
            # 1. EXIF rotation: Crucial for phone camera shots taken in portrait
            img = ImageOps.exif_transpose(img).convert("RGB")

            if not caption or not caption.strip():
                caption = self._extract_caption_date(img)
            else:
                caption = str(caption).strip()[:24]

            # 2. Center crop to 4:3 display ratio (320x240)
            target_ratio = 320.0 / 240.0
            curr_ratio = img.width / img.height

            if curr_ratio > target_ratio:
                new_w = int(img.height * target_ratio)
                left = (img.width - new_w) // 2
                img = img.crop((left, 0, left + new_w, img.height))
            elif curr_ratio < target_ratio:
                new_h = int(img.width / target_ratio)
                top = (img.height - new_h) // 2
                img = img.crop((0, top, img.width, top + new_h))

            # 3. Resize to 320x240 and enhance colors for SPI display
            display_img = img.resize((320, 240), Image.Resampling.LANCZOS)
            try:
                display_img = ImageEnhance.Color(display_img).enhance(1.10)
                display_img = ImageEnhance.Contrast(display_img).enhance(1.05)
            except Exception:
                pass

            # 4. Generate thumbnail for dashboard (160x120)
            thumb_img = display_img.resize((160, 120), Image.Resampling.LANCZOS)

            # Compute image fingerprints for duplicate detection
            raw_hash = hashlib.md5(raw).hexdigest()
            pixel_hash = hashlib.md5(display_img.tobytes()).hexdigest()
            curr_dhash = self._calc_dhash(display_img)

            # Check for existing duplicate if replace_duplicates is enabled
            existing_match_idx = -1
            if self.replace_duplicates:
                for idx, p in enumerate(self.photos):
                    if p.get("raw_hash") and p["raw_hash"] == raw_hash:
                        existing_match_idx = idx
                        break
                    if p.get("pixel_hash") and p["pixel_hash"] == pixel_hash:
                        existing_match_idx = idx
                        break
                    if p.get("dhash") and self._hamming_distance(p["dhash"], curr_dhash) <= 4:
                        existing_match_idx = idx
                        break

            if existing_match_idx >= 0:
                # DUPLICATE FOUND: Replace existing image in-place (do not duplicate!)
                existing = self.photos.pop(existing_match_idx)
                lib_file = existing["filename"]
                thumb_file = existing["thumb"]

                # Overwrite the image on disk
                display_img.save(os.path.join(self.library_dir, lib_file), "JPEG", quality=92)
                thumb_img.save(os.path.join(self.thumbs_dir, thumb_file), "JPEG", quality=85)

                if caption and caption.strip():
                    existing["caption"] = caption
                existing["added_at"] = datetime.now().isoformat()
                existing["source"] = source
                existing["raw_hash"] = raw_hash
                existing["pixel_hash"] = pixel_hash
                existing["dhash"] = curr_dhash
                existing["is_replaced"] = True

                # Put at front of list (latest)
                self.photos.insert(0, existing)
                self._save_index()
                logger.info(f"Duplicate photo detected: replaced existing memory '{existing['id']}' ({existing.get('caption')}) without duplicating.")

                if notify and hub and hub.connected:
                    await hub.send_json({
                        "cmd": "NOTIF",
                        "app": "Memories",
                        "title": "Photo Replaced",
                        "body": existing.get("caption") or "Duplicate updated"
                    })

                return existing

            # BRAND NEW PHOTO
            photo_id = f"mem_{int(time.time())}_{uuid.uuid4().hex[:6]}"
            lib_file = f"{photo_id}.jpg"
            thumb_file = f"{photo_id}.jpg"

            display_img.save(os.path.join(self.library_dir, lib_file), "JPEG", quality=92)
            thumb_img.save(os.path.join(self.thumbs_dir, thumb_file), "JPEG", quality=85)

            item = {
                "id": photo_id,
                "filename": lib_file,
                "thumb": thumb_file,
                "caption": caption,
                "added_at": datetime.now().isoformat(),
                "source": source,
                "raw_hash": raw_hash,
                "pixel_hash": pixel_hash,
                "dhash": curr_dhash,
                "is_replaced": False
            }

            self.photos.insert(0, item)

            # Prune oldest if storage limit exceeded (FIFO rolling buffer: keeps latest 50)
            while len(self.photos) > self.max_photos:
                old = self.photos.pop()
                self._delete_disk_files(old)

            self._save_index()
            logger.info(f"Successfully ingested memory '{photo_id}' ({caption}) from {source}")

            # Notify LUMO companion visually if connected and notify is enabled (silent, no haptic buzz)
            if notify and hub and hub.connected:
                await hub.send_json({
                    "cmd": "NOTIF",
                    "app": "Memories",
                    "title": "New Photo Added!",
                    "body": caption
                })

            return item

        except Exception as e:
            logger.error(f"Failed to ingest image bytes: {e}")
            return None

    def _delete_disk_files(self, photo: dict):
        try:
            lib_p = os.path.join(self.library_dir, photo.get("filename", ""))
            thumb_p = os.path.join(self.thumbs_dir, photo.get("thumb", ""))
            if os.path.exists(lib_p): os.remove(lib_p)
            if os.path.exists(thumb_p): os.remove(thumb_p)
        except Exception as e:
            logger.warning(f"Error removing disk files for {photo.get('id')}: {e}")

    def delete_photo(self, photo_id: str) -> bool:
        idx = next((i for i, p in enumerate(self.photos) if p["id"] == photo_id), -1)
        if idx == -1:
            return False

        photo = self.photos.pop(idx)
        self._delete_disk_files(photo)
        self._save_index()

        if self.current_index >= len(self.photos):
            self.current_index = max(0, len(self.photos) - 1)

        logger.info(f"Deleted memory photo {photo_id}")
        return True

    def list_photos(self) -> List[Dict[str, Any]]:
        return [
            {
                **p,
                "url": f"/static/memories/library/{p['filename']}",
                "thumb_url": f"/static/memories/thumbs/{p['thumb']}"
            }
            for p in self.photos
        ]

    def get_current(self) -> Optional[Dict[str, Any]]:
        if not self.photos:
            return None
        self.current_index = self.current_index % len(self.photos)
        return self.photos[self.current_index]

    async def push_current(self, hub) -> bool:
        """Streams the current memory to ESP32 over WebSocket in 12 RGB565 strips."""
        photo = self.get_current()
        if not photo or not hub or not hub.connected:
            return False

        lib_path = os.path.join(self.library_dir, photo["filename"])
        if not os.path.exists(lib_path):
            return False

        try:
            img = Image.open(lib_path).convert("RGB")
            if img.size != (320, 240):
                img = img.resize((320, 240), Image.Resampling.LANCZOS)

            caption = (photo.get("caption") or "")[:23]

            # 1. Metadata frame to clear screen and set caption
            await hub.send_json({
                "cmd": "MEMORY_META",
                "caption": caption,
                "strip_count": 12
            })
            await asyncio.sleep(0.02)

            # 2. Stream 12 horizontal strips (320x20 pixels each = 12,800 bytes)
            strip_w = 320
            strip_h = 20
            total_strips = 12

            for i in range(total_strips):
                y_off = i * strip_h
                frame = bytearray(8 + strip_w * strip_h * 2)

                frame[0] = 0xAA
                frame[1] = 0xCC # Frame type: MEMORY_STRIP
                frame[2] = y_off & 0xFF
                frame[3] = (y_off >> 8) & 0xFF
                frame[4] = strip_h & 0xFF
                frame[5] = (strip_h >> 8) & 0xFF
                frame[6] = strip_w & 0xFF
                frame[7] = (strip_w >> 8) & 0xFF

                idx = 8
                for y in range(y_off, y_off + strip_h):
                    for x in range(strip_w):
                        r, g, b = img.getpixel((x, y))
                        rgb565 = self._rgb888_to_rgb565(r, g, b)
                        if self.swap_bytes:
                            frame[idx]     = rgb565 & 0xFF
                            frame[idx + 1] = (rgb565 >> 8) & 0xFF
                        else:
                            frame[idx]     = (rgb565 >> 8) & 0xFF
                            frame[idx + 1] = rgb565 & 0xFF
                        idx += 2

                await hub.send_binary(bytes(frame))
                await asyncio.sleep(0.015) # 15ms delay per strip

            logger.info(f"Streamed memory '{photo.get('id')}' to ESP32 ({caption})")
            return True

        except Exception as e:
            logger.error(f"Failed to push memory to ESP32: {e}")
            return False

    async def next_photo(self, hub=None) -> Optional[Dict[str, Any]]:
        if not self.photos:
            return None
        self.current_index = (self.current_index + 1) % len(self.photos)
        if hub:
            await self.push_current(hub)
        return self.get_current()

    async def prev_photo(self, hub=None) -> Optional[Dict[str, Any]]:
        if not self.photos:
            return None
        self.current_index = (self.current_index - 1) % len(self.photos)
        if hub:
            await self.push_current(hub)
        return self.get_current()
