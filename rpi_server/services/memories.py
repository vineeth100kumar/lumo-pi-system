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
from services.vision_curator import VisionCurator

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
        self.gif_loops = 3  # How many times to loop a GIF before advancing
        self.active_gif_task: Optional[asyncio.Task] = None
        self.gif_cancel_event = asyncio.Event()
        self._gif_cache: Dict[str, List[List[bytes]]] = {}
        self.swap_bytes = True
        self.bgr_mode = False

        # AI Vision Curation (Portraits & Nature Only)
        self.curator = VisionCurator()
        self.curate_display = True

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
                    self.gif_loops = data.get("gif_loops", 3)
                    self.curate_display = data.get("curate_display", True)

                    # Backfill fingerprint hashes and curation for existing library if missing
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
                        if "category" not in p:
                            p["category"] = "nature"
                            p["curated"] = True

                    # Enforce max quota on existing library
                    while len(self.photos) > self.max_photos:
                        old = self.photos.pop()
                        self._delete_disk_files(old)

                    logger.info(f"Loaded {len(self.photos)} memories from index (Quota: {self.max_photos} max FIFO rolling buffer, Curate: {self.curate_display}).")
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
                    "gif_loops": self.gif_loops,
                    "curate_display": self.curate_display,
                    "updated_at": datetime.now().isoformat()
                }, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save memories index: {e}")

    def set_gif_loops(self, loops: int):
        self.gif_loops = max(1, loops)
        self._save_index()

    def is_gif_streaming(self) -> bool:
        return self.active_gif_task is not None and not self.active_gif_task.done()

    def stop_gif_playback(self):
        """Immediately signals any active GIF streaming task to stop."""
        self.gif_cancel_event.set()
        if self.active_gif_task and not self.active_gif_task.done():
            self.active_gif_task.cancel()
        self.active_gif_task = None
        self.gif_cancel_event = asyncio.Event()

    def _crop_to_4_3(self, img: Image.Image) -> Image.Image:
        """Center-crops image to 4:3 (320:240) aspect ratio."""
        target_ratio = 320.0 / 240.0
        curr_ratio = img.width / img.height
        if curr_ratio > target_ratio:
            new_w = int(img.height * target_ratio)
            left = (img.width - new_w) // 2
            return img.crop((left, 0, left + new_w, img.height))
        elif curr_ratio < target_ratio:
            new_h = int(img.width / target_ratio)
            top = (img.height - new_h) // 2
            return img.crop((0, top, img.width, top + new_h))
        return img

    def _render_frame_strips(self, img: Image.Image) -> List[bytes]:
        """Converts a 320x240 RGB image into 12 pre-computed binary strip packets."""
        strip_w = 320
        strip_h = 20
        total_strips = 12
        strips = []
        for i in range(total_strips):
            y_off = i * strip_h
            frame = bytearray(8 + strip_w * strip_h * 2)
            frame[0] = 0xAA
            frame[1] = 0xCC  # Frame type: MEMORY_STRIP
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
            strips.append(bytes(frame))
        return strips

    def _save_binpack(self, photo_id: str, all_frames_strips: List[List[bytes]]):
        """Persists pre-rendered RGB565 strips to library/{photo_id}.binpack."""
        binpack_path = os.path.join(self.library_dir, f"{photo_id}.binpack")
        try:
            with open(binpack_path, "wb") as f:
                for frame in all_frames_strips:
                    for strip in frame:
                        f.write(strip)
        except Exception as e:
            logger.warning(f"Failed to save binpack for {photo_id}: {e}")

    def _load_gif_strips(self, photo_id: str) -> Optional[List[List[bytes]]]:
        """Loads pre-rendered strips from memory cache or disk binpack."""
        if photo_id in self._gif_cache:
            return self._gif_cache[photo_id]

        binpack_path = os.path.join(self.library_dir, f"{photo_id}.binpack")
        if os.path.exists(binpack_path):
            try:
                with open(binpack_path, "rb") as f:
                    data = f.read()
                strip_size = 12808
                strips_per_frame = 12
                frame_size = strip_size * strips_per_frame
                num_frames = len(data) // frame_size
                all_frames = []
                for f_idx in range(num_frames):
                    frame_data = data[f_idx * frame_size : (f_idx + 1) * frame_size]
                    frame_strips = [
                        frame_data[s_idx * strip_size : (s_idx + 1) * strip_size]
                        for s_idx in range(strips_per_frame)
                    ]
                    all_frames.append(frame_strips)
                self._gif_cache[photo_id] = all_frames
                return all_frames
            except Exception as e:
                logger.warning(f"Failed to read binpack for {photo_id}: {e}")

        return None

    def _get_or_load_strips(self, photo: dict) -> Optional[List[List[bytes]]]:
        """Returns pre-rendered binary strips for a photo/gif, generating on-demand if missing."""
        photo_id = photo.get("id", "")
        cached = self._load_gif_strips(photo_id)
        if cached:
            return cached

        # Generate on-the-fly from disk image
        filename = photo.get("filename", "")
        file_path = os.path.join(self.library_dir, filename)
        if not os.path.exists(file_path):
            file_path = os.path.join(self.thumbs_dir, photo.get("thumb", ""))
            if not os.path.exists(file_path):
                return None

        try:
            with Image.open(file_path) as img:
                is_anim = getattr(img, "is_animated", False) and getattr(img, "n_frames", 1) > 1
                if is_anim:
                    num_frames = min(16, img.n_frames)
                    step = img.n_frames / num_frames
                    all_frames = []
                    for i in range(num_frames):
                        img.seek(int(i * step))
                        f_rgb = Image.new("RGB", img.size, (0, 0, 0))
                        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                            rgba = img.convert("RGBA")
                            f_rgb.paste(rgba, (0, 0), rgba)
                        else:
                            f_rgb.paste(img.convert("RGB"), (0, 0))
                        f_rgb = self._crop_to_4_3(ImageOps.exif_transpose(f_rgb)).resize((320, 240), Image.Resampling.LANCZOS)
                        all_frames.append(self._render_frame_strips(f_rgb))
                else:
                    f_rgb = ImageOps.exif_transpose(img.convert("RGB"))
                    f_rgb = self._crop_to_4_3(f_rgb).resize((320, 240), Image.Resampling.LANCZOS)
                    all_frames = [self._render_frame_strips(f_rgb)]

                self._save_binpack(photo_id, all_frames)
                self._gif_cache[photo_id] = all_frames
                return all_frames
        except Exception as e:
            logger.error(f"Failed to generate strips on-the-fly for {photo_id}: {e}")
            return None

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
        """Shared processing core for Bluetooth OBEX, Web Upload, and iOS Shortcuts (supports both static photos and animated GIFs)."""
        if not raw:
            return None

        try:
            raw_img = Image.open(io.BytesIO(raw))
            is_gif = getattr(raw_img, "is_animated", False) and getattr(raw_img, "n_frames", 1) > 1

            if is_gif:
                num_src_frames = raw_img.n_frames
                target_count = min(16, num_src_frames)
                step = num_src_frames / target_count
                sample_indices = [int(i * step) for i in range(target_count)]

                frames_320 = []
                for s_idx in sample_indices:
                    raw_img.seek(s_idx)
                    f_rgb = Image.new("RGB", raw_img.size, (0, 0, 0))
                    if raw_img.mode in ("RGBA", "LA") or (raw_img.mode == "P" and "transparency" in raw_img.info):
                        rgba = raw_img.convert("RGBA")
                        f_rgb.paste(rgba, (0, 0), rgba)
                    else:
                        f_rgb.paste(raw_img.convert("RGB"), (0, 0))

                    f_rgb = ImageOps.exif_transpose(f_rgb)
                    f_rgb = self._crop_to_4_3(f_rgb)
                    f_rgb = f_rgb.resize((320, 240), Image.Resampling.LANCZOS)
                    try:
                        f_rgb = ImageEnhance.Color(f_rgb).enhance(1.10)
                        f_rgb = ImageEnhance.Contrast(f_rgb).enhance(1.05)
                    except Exception:
                        pass
                    frames_320.append(f_rgb)

                display_img = frames_320[0]
                thumb_img = display_img.resize((160, 120), Image.Resampling.LANCZOS)
            else:
                img = ImageOps.exif_transpose(raw_img).convert("RGB")
                img = self._crop_to_4_3(img)
                display_img = img.resize((320, 240), Image.Resampling.LANCZOS)
                try:
                    display_img = ImageEnhance.Color(display_img).enhance(1.10)
                    display_img = ImageEnhance.Contrast(display_img).enhance(1.05)
                except Exception:
                    pass
                thumb_img = display_img.resize((160, 120), Image.Resampling.LANCZOS)
                frames_320 = [display_img]

            if not caption or not caption.strip():
                caption = self._extract_caption_date(raw_img)
            else:
                caption = str(caption).strip()[:24]

            # Analyze image content with VisionCurator (Portraits & Nature classification)
            curation_res = self.curator.classify(display_img)

            # Pre-render binary strips for all frames (12 strips per frame)
            all_frame_strips = [self._render_frame_strips(f) for f in frames_320]

            # Fingerprints for deduplication
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
                photo_id = existing["id"]

                # Remove old files (could be converting jpg <-> gif)
                self._delete_disk_files(existing)

                ext = ".gif" if is_gif else ".jpg"
                lib_file = f"{photo_id}{ext}"
                thumb_file = f"{photo_id}.jpg"

                if is_gif:
                    frames_320[0].save(
                        os.path.join(self.library_dir, lib_file),
                        save_all=True,
                        append_images=frames_320[1:],
                        loop=0,
                        duration=160,
                        optimize=True
                    )
                else:
                    display_img.save(os.path.join(self.library_dir, lib_file), "JPEG", quality=92)

                thumb_img.save(os.path.join(self.thumbs_dir, thumb_file), "JPEG", quality=85)
                self._save_binpack(photo_id, all_frame_strips)
                self._gif_cache[photo_id] = all_frame_strips

                if caption and caption.strip():
                    existing["caption"] = caption
                existing["filename"] = lib_file
                existing["thumb"] = thumb_file
                existing["is_gif"] = is_gif
                existing["frame_count"] = len(frames_320)
                existing["added_at"] = datetime.now().isoformat()
                existing["source"] = source
                existing["raw_hash"] = raw_hash
                existing["pixel_hash"] = pixel_hash
                existing["dhash"] = curr_dhash
                existing["is_replaced"] = True

                # Update classification if not manually overridden
                if existing.get("curated_override") is None:
                    existing["category"] = curation_res.get("category", "nature")
                    existing["curated"] = curation_res.get("curated", True)
                    existing["face_count"] = curation_res.get("face_count", 0)
                    existing["nature_score"] = curation_res.get("nature_score", 0.0)
                    existing["subtype"] = curation_res.get("subtype", "")
                    existing["classification_tags"] = curation_res.get("tags", [])
                    existing["classification_reason"] = curation_res.get("reason", "")

                self.photos.insert(0, existing)
                self._save_index()
                logger.info(f"Duplicate photo detected: replaced existing memory '{photo_id}' ({existing.get('caption')}, is_gif={is_gif}, category={existing.get('category')}) without duplicating.")

                if notify and hub and hub.connected:
                    await hub.send_json({
                        "cmd": "NOTIF",
                        "app": "Memories",
                        "title": "Photo Replaced",
                        "body": existing.get("caption") or "Duplicate updated"
                    })

                return existing

            # BRAND NEW MEMORY
            photo_id = f"mem_{int(time.time())}_{uuid.uuid4().hex[:6]}"
            ext = ".gif" if is_gif else ".jpg"
            lib_file = f"{photo_id}{ext}"
            thumb_file = f"{photo_id}.jpg"

            if is_gif:
                frames_320[0].save(
                    os.path.join(self.library_dir, lib_file),
                    save_all=True,
                    append_images=frames_320[1:],
                    loop=0,
                    duration=160,
                    optimize=True
                )
            else:
                display_img.save(os.path.join(self.library_dir, lib_file), "JPEG", quality=92)

            thumb_img.save(os.path.join(self.thumbs_dir, thumb_file), "JPEG", quality=85)
            self._save_binpack(photo_id, all_frame_strips)
            self._gif_cache[photo_id] = all_frame_strips

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
                "is_gif": is_gif,
                "frame_count": len(frames_320),
                "is_replaced": False,
                "category": curation_res.get("category", "nature"),
                "curated": curation_res.get("curated", True),
                "face_count": curation_res.get("face_count", 0),
                "nature_score": curation_res.get("nature_score", 0.0),
                "subtype": curation_res.get("subtype", ""),
                "classification_tags": curation_res.get("tags", []),
                "classification_reason": curation_res.get("reason", ""),
                "curated_override": None
            }

            self.photos.insert(0, item)

            while len(self.photos) > self.max_photos:
                old = self.photos.pop()
                self._delete_disk_files(old)

            self._save_index()
            logger.info(f"Successfully ingested memory '{photo_id}' ({caption}, is_gif={is_gif}, category={item['category']}) from {source}")

            if notify and hub and hub.connected:
                await hub.send_json({
                    "cmd": "NOTIF",
                    "app": "Memories",
                    "title": "New Memory Added!",
                    "body": caption
                })

            return item

        except Exception as e:
            logger.error(f"Failed to ingest image bytes: {e}")
            return None

    def _delete_disk_files(self, photo: dict):
        try:
            pid = photo.get("id", "")
            for ext in (".jpg", ".gif", ".binpack"):
                p = os.path.join(self.library_dir, f"{pid}{ext}")
                if os.path.exists(p):
                    try: os.remove(p)
                    except Exception: pass
            lib_p = os.path.join(self.library_dir, photo.get("filename", ""))
            if os.path.exists(lib_p):
                try: os.remove(lib_p)
                except Exception: pass
            thumb_p = os.path.join(self.thumbs_dir, photo.get("thumb", ""))
            if os.path.exists(thumb_p):
                try: os.remove(thumb_p)
                except Exception: pass
            if pid in self._gif_cache:
                del self._gif_cache[pid]
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

    def get_displayable_photos(self) -> List[Dict[str, Any]]:
        """Returns photos eligible for display on the ESP32 desk screen."""
        if not self.photos:
            return []
        if not self.curate_display:
            return self.photos

        # Filter to only portraits & nature (or photos with manual positive override)
        curated = [
            p for p in self.photos
            if (p.get("curated_override") is True) or
               (p.get("curated_override") is not False and p.get("category", "nature") in ("portrait", "nature"))
        ]
        # Graceful fallback: if no photos match, display all photos rather than black screen
        return curated if curated else self.photos

    def get_current(self) -> Optional[Dict[str, Any]]:
        displayable = self.get_displayable_photos()
        if not displayable:
            return None
        self.current_index = self.current_index % len(displayable)
        return displayable[self.current_index]

    def select_photo(self, photo_id: str) -> Optional[Dict[str, Any]]:
        displayable = self.get_displayable_photos()
        for idx, p in enumerate(displayable):
            if p.get("id") == photo_id:
                self.current_index = idx
                return p
        # If not in displayable (e.g. filtered out), locate in all photos
        for p in self.photos:
            if p.get("id") == photo_id:
                return p
        return None

    def scan_and_curate_all(self) -> Dict[str, Any]:
        """Retroactively analyzes and classifies all photos in library."""
        counts = {"total": len(self.photos), "curated": 0, "portrait": 0, "nature": 0, "other": 0}
        for p in self.photos:
            if p.get("curated_override") is not None:
                cat = p.get("category", "other")
                counts[cat] = counts.get(cat, 0) + 1
                if p.get("curated"):
                    counts["curated"] += 1
                continue

            lib_p = os.path.join(self.library_dir, p.get("filename", ""))
            thumb_p = os.path.join(self.thumbs_dir, p.get("thumb", ""))
            target_path = lib_p if os.path.exists(lib_p) else thumb_p

            if os.path.exists(target_path):
                try:
                    with Image.open(target_path) as img:
                        res = self.curator.classify(img)
                        p["category"] = res.get("category", "nature")
                        p["curated"] = res.get("curated", True)
                        p["face_count"] = res.get("face_count", 0)
                        p["nature_score"] = res.get("nature_score", 0.0)
                        p["subtype"] = res.get("subtype", "")
                        p["classification_tags"] = res.get("tags", [])
                        p["classification_reason"] = res.get("reason", "")
                except Exception as e:
                    logger.warning(f"Failed to classify photo {p.get('id')}: {e}")

            cat = p.get("category", "nature")
            counts[cat] = counts.get(cat, 0) + 1
            if p.get("curated", True):
                counts["curated"] += 1

        self._save_index()
        logger.info(f"Retroactive curation scan complete: {counts}")
        return counts

    def set_photo_category_override(self, photo_id: str, category: str) -> Optional[Dict[str, Any]]:
        category = category.lower().strip()
        if category not in ("portrait", "nature", "other"):
            return None
        for p in self.photos:
            if p.get("id") == photo_id:
                p["category"] = category
                p["curated"] = (category in ("portrait", "nature"))
                p["curated_override"] = (category in ("portrait", "nature"))
                self._save_index()
                return p
        return None

    def get_curation_stats(self) -> Dict[str, Any]:
        displayable = self.get_displayable_photos()
        portraits = sum(1 for p in self.photos if p.get("category") == "portrait")
        nature = sum(1 for p in self.photos if p.get("category") == "nature")
        other = sum(1 for p in self.photos if p.get("category") == "other")
        is_cv = getattr(self.curator, "is_available", False)
        return {
            "curate_display": self.curate_display,
            "opencv_available": is_cv,
            "engine": "OpenCV Haar Cascades + Nature Engine" if is_cv else "Pass-Through (OpenCV missing)",
            "total": len(self.photos),
            "total_photos": len(self.photos),
            "curated_displayable": len(displayable),
            "displayable_count": len(displayable),
            "portrait": portraits,
            "portraits_count": portraits,
            "nature": nature,
            "nature_count": nature,
            "other": other,
            "filtered_count": other,
        }

    async def push_current(self, hub, on_advance=None) -> bool:
        """Streams current memory (static frame or GIF animation loop) to ESP32."""
        photo = self.get_current()
        if not photo or not hub or not hub.connected:
            return False

        # Stop any running animation loop first
        self.stop_gif_playback()

        all_frames = self._get_or_load_strips(photo)
        if not all_frames:
            return False

        caption = (photo.get("caption") or "")[:23]

        # Send metadata once to set caption and clear screen
        await hub.send_json({
            "cmd": "MEMORY_META",
            "caption": caption,
            "strip_count": 12
        })
        await asyncio.sleep(0.02)

        is_gif = bool(photo.get("is_gif")) and len(all_frames) > 1

        if is_gif:
            self.active_gif_task = asyncio.create_task(
                self._stream_gif_loop(photo, all_frames, hub, on_advance=on_advance)
            )
            return True
        else:
            # Single static frame
            for strip in all_frames[0]:
                await hub.send_binary(strip)
                await asyncio.sleep(0.015)
            logger.info(f"Streamed static memory '{photo.get('id')}' to ESP32 ({caption})")
            return True

    async def _stream_gif_loop(self, photo: dict, all_frames: List[List[bytes]], hub, on_advance=None):
        photo_id = photo.get("id", "")
        loops_to_play = photo.get("gif_loops", self.gif_loops)
        if loops_to_play <= 0:
            loops_to_play = 999999

        logger.info(f"Starting GIF streaming for '{photo_id}' ({len(all_frames)} frames, {loops_to_play} loops)")
        try:
            for loop_num in range(loops_to_play):
                if self.gif_cancel_event.is_set():
                    break

                for frame_strips in all_frames:
                    if self.gif_cancel_event.is_set():
                        break

                    for strip in frame_strips:
                        if self.gif_cancel_event.is_set():
                            break
                        await hub.send_binary(strip)
                        await asyncio.sleep(0.012)

                    await asyncio.sleep(0.04)

            logger.info(f"GIF playback finished for '{photo_id}' ({loops_to_play} loops completed)")

            if not self.gif_cancel_event.is_set() and on_advance:
                await on_advance()

        except asyncio.CancelledError:
            logger.debug(f"GIF streaming cancelled for '{photo_id}'")
        except Exception as e:
            logger.error(f"Error during GIF streaming for '{photo_id}': {e}")

    async def next_photo(self, hub=None, on_advance=None) -> Optional[Dict[str, Any]]:
        displayable = self.get_displayable_photos()
        if not displayable:
            return None
        self.stop_gif_playback()
        self.current_index = (self.current_index + 1) % len(displayable)
        if hub:
            await self.push_current(hub, on_advance=on_advance)
        return self.get_current()

    async def prev_photo(self, hub=None, on_advance=None) -> Optional[Dict[str, Any]]:
        displayable = self.get_displayable_photos()
        if not displayable:
            return None
        self.stop_gif_playback()
        self.current_index = (self.current_index - 1) % len(displayable)
        if hub:
            await self.push_current(hub, on_advance=on_advance)
        return self.get_current()
