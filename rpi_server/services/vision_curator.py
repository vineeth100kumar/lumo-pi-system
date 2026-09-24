import io
import os
import logging
from typing import Dict, Any, List, Optional, Union
from PIL import Image

logger = logging.getLogger("VisionCurator")

try:
    import cv2
    import numpy as np
    OPENCV_AVAILABLE = True
except ImportError:
    cv2 = None
    np = None
    OPENCV_AVAILABLE = False
    logger.warning("OpenCV not available. Vision curation will run in pass-through mode.")


class VisionCurator:
    """
    Intelligent Computer Vision classifier for LUMO Memories.
    Recognizes:
      1. Human Faces & Figures (Portraits: close-up, single, group, figures)
      2. Nature-based Images (Landscapes, greenery/foliage, bodies of water, sky, sunsets, flowers)
      3. Rejects non-scenic clutter (Screenshots, documents, receipts, flat graphics, indoor objects)
    """

    def __init__(self):
        self.face_cascade = None
        self.face_cascade_alt2 = None
        self.face_cascade_default = None
        self.face_cascade_alt = None
        self.profile_cascade = None
        self.eye_cascade = None
        self._init_models()

    def _find_cascade(self, filename: str) -> Optional[Any]:
        if not OPENCV_AVAILABLE:
            return None
        import sys
        import glob
        candidates = []

        # 0. Repo-bundled cascades/ directory — always works regardless of OpenCV version/platform
        #    Located at rpi_server/cascades/ (sibling of services/)
        local_cascades = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cascades", filename)
        candidates.append(os.path.normpath(local_cascades))

        # 1. cv2.data.haarcascades (works for standard pip install)
        haar_dir = getattr(cv2, "data", None)
        if haar_dir and hasattr(haar_dir, "haarcascades"):
            hd = str(haar_dir.haarcascades)
            candidates.append(os.path.join(hd, filename))
            # haarcascades may be a path that ends with separator already
            if not hd.endswith(os.sep):
                candidates.append(hd + os.sep + filename)

        # 2. cv2 package directory (covers headless builds)
        if hasattr(cv2, "__file__") and cv2.__file__:
            cv2_dir = os.path.dirname(cv2.__file__)
            candidates.append(os.path.join(cv2_dir, "data", filename))
            candidates.append(os.path.join(cv2_dir, filename))

        # 3. Scan ALL python paths / site-packages for any cv2 installation
        for sp in sys.path:
            candidates.append(os.path.join(sp, "cv2", "data", filename))
            candidates.append(os.path.join(sp, "cv2-python", "data", filename))

        # 4. Glob-search inside the active venv (handles cv2/cv2.cpython-*.so sibling dirs)
        for prefix in [os.path.dirname(os.path.dirname(sys.executable)), sys.prefix]:
            for hit in glob.glob(os.path.join(prefix, "**", "cv2", "data", filename), recursive=True):
                candidates.append(hit)
            for hit in glob.glob(os.path.join(prefix, "**", "haarcascades", filename), recursive=True):
                candidates.append(hit)

        # 5. Standard Raspberry Pi OS / Debian system paths
        for base in (
            "/usr/share/opencv4/haarcascades",
            "/usr/share/opencv/haarcascades",
            "/usr/local/share/opencv4/haarcascades",
            "/usr/share/java/opencv-4/haarcascades",
        ):
            candidates.append(os.path.join(base, filename))

        seen = set()
        for p in candidates:
            if p in seen:
                continue
            seen.add(p)
            if os.path.exists(p):
                try:
                    c = cv2.CascadeClassifier(p)
                    if c is not None and not c.empty():
                        logger.debug(f"  Loaded cascade from: {p}")
                        return c
                except Exception:
                    pass
        return None

    def _init_models(self):
        if not OPENCV_AVAILABLE:
            return
        try:
            self.face_cascade_alt2 = self._find_cascade("haarcascade_frontalface_alt2.xml")
            self.face_cascade_default = self._find_cascade("haarcascade_frontalface_default.xml")
            self.face_cascade_alt = self._find_cascade("haarcascade_frontalface_alt.xml")
            self.profile_cascade = self._find_cascade("haarcascade_profileface.xml")
            self.eye_cascade = self._find_cascade("haarcascade_eye.xml")

            self.face_cascade = self.face_cascade_alt2 or self.face_cascade_default or self.face_cascade_alt

            loaded = sum(1 for c in (self.face_cascade_alt2, self.face_cascade_default, self.face_cascade_alt,
                                    self.profile_cascade, self.eye_cascade) if c is not None)

            if loaded > 0:
                logger.info(f"VisionCurator initialized: {loaded} face detection models loaded.")
            else:
                # Last-resort: try installing data files via opencv-python (not headless)
                logger.warning("VisionCurator: No Haar cascade XMLs found. Face detection inactive, but Nature & Document curation active.")
                logger.warning("  Fix: run 'pip install opencv-python' in your venv, or install 'python3-opencv' system package.")
        except Exception as e:
            logger.warning(f"Could not load Haar cascades: {e}")

    @property
    def is_available(self) -> bool:
        return bool(OPENCV_AVAILABLE)

    @property
    def loaded_cascade_count(self) -> int:
        """How many Haar cascade models are currently loaded (0 means face detection inactive)."""
        return sum(1 for c in (
            getattr(self, "face_cascade_alt2", None),
            getattr(self, "face_cascade_default", None),
            getattr(self, "face_cascade_alt", None),
            getattr(self, "profile_cascade", None),
            getattr(self, "eye_cascade", None),
        ) if c is not None)

    def classify(self, img_input: Union[Image.Image, bytes, "np.ndarray"]) -> Dict[str, Any]:
        """
        Classifies an image into:
          - 'portrait': One or more human faces or portrait figures detected.
          - 'nature': Landscapes, greenery, sky, water, sunsets, flora.
          - 'other': Screenshots, receipts, documents, indoor clutter, flat graphics.

        Returns structured dict with category, curated flag, confidence, face_count, and tags.
        """
        if not OPENCV_AVAILABLE:
            # Fallback if OpenCV not installed
            return {
                "category": "nature",
                "curated": True,
                "confidence": 0.50,
                "face_count": 0,
                "face_boxes": [],
                "nature_score": 0.50,
                "subtype": "unclassified",
                "tags": ["nature", "auto"],
                "reason": "OpenCV not available, default allow"
            }

        try:
            # 1. Standardize input to BGR numpy array
            bgr = self._to_bgr_array(img_input)
            if bgr is None or bgr.size == 0:
                return {
                    "category": "other",
                    "curated": False,
                    "confidence": 0.0,
                    "face_count": 0,
                    "face_boxes": [],
                    "nature_score": 0.0,
                    "subtype": "invalid",
                    "tags": ["invalid"],
                    "reason": "Failed to decode image data"
                }

            h, w = bgr.shape[:2]

            # 2. Stage 1: Face & Portrait Detection (Multi-scale high sensitivity)
            portrait_res = self._detect_faces(bgr)
            if portrait_res is not None:
                portrait_res.setdefault("face_boxes", [])
                return portrait_res

            # Resize to standardized analysis resolution (320x240) for constant speed in Stages 2 & 3
            analysis_img = cv2.resize(bgr, (320, 240), interpolation=cv2.INTER_AREA)

            # 3. Stage 2: Reject Documents, Screenshots, Flat Graphics & Low-Texture Surfaces
            doc_res = self._detect_document_or_screenshot(analysis_img, orig_w=w, orig_h=h)
            if doc_res is not None:
                doc_res.setdefault("face_boxes", [])
                return doc_res

            # 4. Stage 3: Nature & Scenic Landscape Detection
            nature_res = self._detect_nature_scene(analysis_img)
            nature_res.setdefault("face_boxes", [])
            return nature_res

        except Exception as e:
            logger.error(f"Error classifying image: {e}")
            return {
                "category": "other",
                "curated": False,
                "confidence": 0.30,
                "face_count": 0,
                "face_boxes": [],
                "nature_score": 0.0,
                "subtype": "error",
                "tags": ["error"],
                "reason": str(e)
            }

    def _to_bgr_array(self, img_input: Union[Image.Image, bytes, "np.ndarray"]) -> Optional["np.ndarray"]:
        """Converts PIL Image, bytes, or numpy array to OpenCV BGR format."""
        try:
            if isinstance(img_input, bytes):
                nparr = np.frombuffer(img_input, np.uint8)
                return cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            elif isinstance(img_input, Image.Image):
                rgb = np.array(img_input.convert("RGB"))
                return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            elif isinstance(img_input, np.ndarray):
                if len(img_input.shape) == 2:
                    return cv2.cvtColor(img_input, cv2.COLOR_GRAY2BGR)
                elif img_input.shape[2] == 4:
                    return cv2.cvtColor(img_input, cv2.COLOR_RGBA2BGR)
                return img_input
        except Exception as e:
            logger.error(f"Failed to convert image input to BGR: {e}")
        return None

    @staticmethod
    def _nms_boxes(boxes: list, iou_threshold: float = 0.3) -> list:
        """Remove duplicate/overlapping detections from merged cascade outputs."""
        if not boxes:
            return []
        boxes = sorted(boxes, key=lambda b: b[2] * b[3], reverse=True)
        kept = []
        for box in boxes:
            x1, y1, w1, h1 = box
            duplicate = False
            for kx, ky, kw, kh in kept:
                ix = max(0, min(x1 + w1, kx + kw) - max(x1, kx))
                iy = max(0, min(y1 + h1, ky + kh) - max(y1, ky))
                intersection = ix * iy
                union = w1 * h1 + kw * kh - intersection
                if union > 0 and (intersection / union) > iou_threshold:
                    duplicate = True
                    break
                if (w1 * h1 > 0 and (intersection / (w1 * h1)) > 0.60) or (kw * kh > 0 and (intersection / (kw * kh)) > 0.60):
                    duplicate = True
                    break
            if not duplicate:
                kept.append(box)
        return kept

    def _detect_faces(self, bgr: "np.ndarray") -> Optional[Dict[str, Any]]:
        """Detects human faces & figures using merged multi-cascade NMS without early breaking."""
        if not OPENCV_AVAILABLE:
            return None

        # Upscale smaller images to at least 480x360 so small faces in photos are clear
        h, w = bgr.shape[:2]
        if w < 480 or h < 360:
            scale = max(480.0 / w, 360.0 / h)
            face_img = cv2.resize(bgr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LINEAR)
        elif w > 960 or h > 720:
            scale = min(960.0 / w, 720.0 / h)
            face_img = cv2.resize(bgr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        else:
            face_img = bgr

        fh, fw = face_img.shape[:2]
        gray = cv2.cvtColor(face_img, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray_clahe = clahe.apply(gray)

        all_raw = []
        frontal = [d for d in (self.face_cascade_alt2, self.face_cascade_default, self.face_cascade_alt) if d is not None]

        # Stage 1: ALL frontal cascades on CLAHE (do NOT break early, merge all)
        for det in frontal:
            dets = det.detectMultiScale(
                gray_clahe,
                scaleFactor=1.05,
                minNeighbors=3,
                minSize=(20, 20)
            )
            if len(dets) > 0:
                all_raw.extend(list(dets))

        # Stage 1b: ALL frontal cascades on raw gray
        for det in frontal:
            dets = det.detectMultiScale(
                gray,
                scaleFactor=1.08,
                minNeighbors=3,
                minSize=(20, 20)
            )
            if len(dets) > 0:
                all_raw.extend(list(dets))

        # Merge and deduplicate overlapping frontal face detections
        face_list = self._nms_boxes(all_raw, iou_threshold=0.3)

        # Stage 2: Profile faces (normal and flipped) if no frontal faces found
        if len(face_list) == 0 and self.profile_cascade is not None:
            prof_raw = []
            profiles = self.profile_cascade.detectMultiScale(
                gray_clahe,
                scaleFactor=1.08,
                minNeighbors=3,
                minSize=(20, 20)
            )
            if len(profiles) > 0:
                prof_raw.extend(list(profiles))

            flipped = cv2.flip(gray_clahe, 1)
            flipped_profiles = self.profile_cascade.detectMultiScale(
                flipped,
                scaleFactor=1.08,
                minNeighbors=3,
                minSize=(20, 20)
            )
            if len(flipped_profiles) > 0:
                for (fx, fy, f_w, f_h) in flipped_profiles:
                    orig_x = fw - (fx + f_w)
                    prof_raw.append((orig_x, fy, f_w, f_h))

            if prof_raw:
                face_list = self._nms_boxes(prof_raw, iou_threshold=0.3)

        # Stage 3: Eye pair detection in upper region as last resort
        if len(face_list) == 0 and self.eye_cascade is not None:
            top_gray = gray_clahe[:int(fh * 0.65), :]
            eyes = self.eye_cascade.detectMultiScale(top_gray, scaleFactor=1.10, minNeighbors=4, minSize=(14, 14))
            if len(eyes) >= 2:
                sorted_eyes = sorted(eyes, key=lambda e: e[0])
                e_left, e_right = sorted_eyes[0], sorted_eyes[-1]
                eye_center_x = (e_left[0] + e_right[0] + e_right[2]) / 2.0
                eye_center_y = (e_left[1] + e_right[1] + e_right[3]) / 2.0
                eye_dist = max((e_right[0] + e_right[2]) - e_left[0], 20)
                approx_face_w = int(eye_dist * 2.0)
                approx_face_h = int(approx_face_w * 1.25)
                approx_x = max(0, int(eye_center_x - approx_face_w / 2.0))
                approx_y = max(0, int(eye_center_y - approx_face_h * 0.38))
                approx_x = min(approx_x, fw - 1)
                approx_y = min(approx_y, fh - 1)
                approx_w = min(approx_face_w, fw - approx_x)
                approx_h = min(approx_face_h, fh - approx_y)
                face_list = [(approx_x, approx_y, approx_w, approx_h)]

        if len(face_list) > 0:
            scale_x = w / float(fw)
            scale_y = h / float(fh)
            norm_face_boxes = []
            for (fx, fy, fw2, fh2) in face_list:
                orig_x = fx * scale_x
                orig_y = fy * scale_y
                orig_w = fw2 * scale_x
                orig_h = fh2 * scale_y
                norm_face_boxes.append([
                    float(round(orig_x / float(w), 4)),
                    float(round(orig_y / float(h), 4)),
                    float(round(orig_w / float(w), 4)),
                    float(round(orig_h / float(h), 4))
                ])

            face_count = len(face_list)
            total_img_area = fh * fw
            max_face_area = max(fw2 * fh2 for (fx, fy, fw2, fh2) in face_list)
            face_area_pct = max_face_area / float(total_img_area)

            if face_count >= 3:
                subtype = "group_portrait"
                tag_label = "Group Portrait"
            elif face_area_pct >= 0.08:
                subtype = "close_up"
                tag_label = "Close-up Portrait"
            else:
                subtype = "portrait"
                tag_label = "Portrait"

            confidence = min(0.99, 0.84 + (0.04 * min(3, face_count)))

            return {
                "category": "portrait",
                "curated": True,
                "confidence": round(confidence, 2),
                "face_count": face_count,
                "face_boxes": norm_face_boxes,
                "nature_score": 0.05,
                "subtype": subtype,
                "tags": ["portrait", tag_label, f"{face_count} face{'s' if face_count > 1 else ''}"],
                "reason": f"Detected {face_count} human face(s)"
            }

        return None

    def _detect_document_or_screenshot(self, bgr: "np.ndarray", orig_w: int = 320, orig_h: int = 240) -> Optional[Dict[str, Any]]:
        """Identifies text screenshots, white paper documents, receipts, flat UI, and solid colors."""
        h, w = bgr.shape[:2]
        total_pixels = float(h * w)

        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        hist, _ = np.histogram(gray, bins=32, range=(0, 256))
        max_bin_ratio = np.max(hist) / total_pixels

        # Dominant flat color with no texture (solid background, flat UI, wallpaper, painted walls)
        if max_bin_ratio > 0.45 and lap_var < 50.0:
            return {
                "category": "other",
                "curated": False,
                "confidence": 0.94,
                "face_count": 0,
                "nature_score": 0.01,
                "subtype": "flat_graphic",
                "tags": ["other", "Flat Graphic / UI"],
                "reason": f"Flat uniform color / low texture (ratio={max_bin_ratio:.2f}, var={lap_var:.1f})"
            }

        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        sat = hsv[:, :, 1]
        mean_sat = np.mean(sat) / 255.0

        dominant_val = np.argmax(hist) * 8
        is_white_doc = (dominant_val >= 195 and max_bin_ratio >= 0.30)
        is_dark_screen = (dominant_val <= 35 and max_bin_ratio >= 0.35)

        grad_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        edge_energy_x = np.mean(np.abs(grad_x))

        if (is_white_doc or is_dark_screen) and mean_sat < 0.18:
            return {
                "category": "other",
                "curated": False,
                "confidence": 0.92,
                "face_count": 0,
                "nature_score": 0.02,
                "subtype": "document",
                "tags": ["other", "Document / Text"],
                "reason": "Document / text / screenshot background"
            }

        aspect_ratio = min(orig_w, orig_h) / max(orig_w, orig_h)
        is_phone_aspect = (aspect_ratio <= 0.60)
        if is_phone_aspect and max_bin_ratio >= 0.28 and mean_sat < 0.22:
            return {
                "category": "other",
                "curated": False,
                "confidence": 0.88,
                "face_count": 0,
                "nature_score": 0.04,
                "subtype": "screenshot",
                "tags": ["other", "Phone Screenshot"],
                "reason": "Phone screen aspect ratio with UI flat colors"
            }

        if mean_sat < 0.08 and edge_energy_x > 14.0:
            return {
                "category": "other",
                "curated": False,
                "confidence": 0.90,
                "face_count": 0,
                "nature_score": 0.01,
                "subtype": "document",
                "tags": ["other", "Monochrome Text"],
                "reason": "Monochromatic high-contrast text lines"
            }

        return None

    def _detect_nature_scene(self, bgr: "np.ndarray") -> Dict[str, Any]:
        """Analyzes color palettes, texture, and spatial layout for landscapes and nature."""
        h, w = bgr.shape[:2]
        total_pixels = float(h * w)

        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()

        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        H = hsv[:, :, 0]
        S = hsv[:, :, 1]
        V = hsv[:, :, 2]
        B, G, R = bgr[:, :, 0], bgr[:, :, 1], bgr[:, :, 2]

        # 1. Foliage / Greenery: Must be truly green (G > R*0.95 and G > B) with leaf hue (35..85)
        foliage_mask = (H >= 35) & (H <= 85) & (S >= 35) & (V >= 35) & (G > R * 0.95) & (G > B)
        foliage_ratio = np.count_nonzero(foliage_mask) / total_pixels

        # 2. Sky & Water: Sky at top (B dominant, V >= 65), water throughout (B > R)
        top_half_bgr = bgr[:int(h * 0.55), :, :]
        top_pixels = float(top_half_bgr.shape[0] * top_half_bgr.shape[1])
        top_hsv = hsv[:int(h * 0.55), :, :]

        sky_mask = (top_hsv[:,:,0] >= 90) & (top_hsv[:,:,0] <= 130) & (top_hsv[:,:,1] >= 25) & (top_hsv[:,:,2] >= 65) & (top_half_bgr[:,:,0] > top_half_bgr[:,:,2])
        top_sky_ratio = np.count_nonzero(sky_mask) / top_pixels

        water_mask = (hsv[:,:,0] >= 90) & (hsv[:,:,0] <= 135) & (hsv[:,:,1] >= 30) & (hsv[:,:,2] >= 45) & (B > R)
        water_ratio = np.count_nonzero(water_mask) / total_pixels

        # 3. Sunset / Golden Hour Sky: In TOP 65%, BRIGHT (V >= 170), warm hues (0..24 or 165..180), warm dominant (R > B * 1.2)
        top_sunset_mask = ((top_hsv[:,:,0] <= 24) | (top_hsv[:,:,0] >= 165)) & (top_hsv[:,:,1] >= 60) & (top_hsv[:,:,2] >= 170) & (top_half_bgr[:,:,2] > top_half_bgr[:,:,0] * 1.2)
        sunset_sky_ratio = np.count_nonzero(top_sunset_mask) / top_pixels

        # 4. Floral Blooms: Vibrant pink/purple/yellow with some green foliage present
        floral_mask = (((H >= 140) & (H <= 165) & (S >= 90) & (V >= 100)) | ((H >= 22) & (H <= 35) & (S >= 100) & (V >= 120)))
        floral_ratio = np.count_nonzero(floral_mask) / total_pixels

        # 5. Spatial Horizon Layout: Sky at top, Ground/Greenery at bottom
        bot_half_bgr = bgr[int(h * 0.50):, :, :]
        bot_half_hsv = hsv[int(h * 0.50):, :, :]
        bot_pixels = float(bot_half_bgr.shape[0] * bot_half_bgr.shape[1])
        bot_green = np.count_nonzero((bot_half_hsv[:,:,0] >= 35) & (bot_half_hsv[:,:,0] <= 85) & (bot_half_bgr[:,:,1] > bot_half_bgr[:,:,2])) / bot_pixels

        horizon_landscape = (top_sky_ratio >= 0.20 and bot_green >= 0.15) or (sunset_sky_ratio >= 0.18 and bot_green >= 0.10)

        # Threshold Decision
        if horizon_landscape:
            return {
                "category": "nature",
                "curated": True,
                "confidence": 0.95,
                "face_count": 0,
                "nature_score": round(max(top_sky_ratio, sunset_sky_ratio) + bot_green, 2),
                "subtype": "landscape",
                "tags": ["nature", "Scenic Landscape"],
                "reason": f"Scenic horizon landscape (Sky: {max(top_sky_ratio, sunset_sky_ratio):.0%}, Ground: {bot_green:.0%})"
            }

        if foliage_ratio >= 0.18 and lap_var > 30.0:
            return {
                "category": "nature",
                "curated": True,
                "confidence": min(0.98, round(0.70 + foliage_ratio, 2)),
                "face_count": 0,
                "nature_score": round(foliage_ratio, 2),
                "subtype": "foliage",
                "tags": ["nature", "Greenery & Foliage"],
                "reason": f"Greenery & foliage (Green: {foliage_ratio:.0%}, Texture: {lap_var:.0f})"
            }

        if top_sky_ratio >= 0.30:
            return {
                "category": "nature",
                "curated": True,
                "confidence": 0.92,
                "face_count": 0,
                "nature_score": round(top_sky_ratio, 2),
                "subtype": "sky",
                "tags": ["nature", "Open Sky Scenery"],
                "reason": f"Open sky scenery ({top_sky_ratio:.0%})"
            }

        if water_ratio >= 0.25:
            return {
                "category": "nature",
                "curated": True,
                "confidence": 0.90,
                "face_count": 0,
                "nature_score": round(water_ratio, 2),
                "subtype": "water",
                "tags": ["nature", "Ocean & Water"],
                "reason": f"Body of water / ocean ({water_ratio:.0%})"
            }

        if sunset_sky_ratio >= 0.20:
            return {
                "category": "nature",
                "curated": True,
                "confidence": 0.94,
                "face_count": 0,
                "nature_score": round(sunset_sky_ratio, 2),
                "subtype": "sunset",
                "tags": ["nature", "Sunset & Golden Hour"],
                "reason": f"Glowing sunset / golden hour sky ({sunset_sky_ratio:.0%})"
            }

        if floral_ratio >= 0.10 and foliage_ratio >= 0.05:
            return {
                "category": "nature",
                "curated": True,
                "confidence": 0.92,
                "face_count": 0,
                "nature_score": round(floral_ratio + foliage_ratio, 2),
                "subtype": "flowers",
                "tags": ["nature", "Floral & Blooms"],
                "reason": f"Floral blooms with natural greenery ({floral_ratio:.0%})"
            }

        # Otherwise: Indoor, clutter, random objects, etc.
        return {
            "category": "other",
            "curated": False,
            "confidence": 0.88,
            "face_count": 0,
            "nature_score": round(max(foliage_ratio, top_sky_ratio, sunset_sky_ratio), 2),
            "subtype": "indoor_or_clutter",
            "tags": ["other", "Indoor / Clutter"],
            "reason": "Insufficient portrait or natural scenery scores"
        }
