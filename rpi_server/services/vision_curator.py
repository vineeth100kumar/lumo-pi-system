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
      1. Human Faces (Portraits: close-up, single, group)
      2. Nature-based Images (Landscapes, foliage/greenery, bodies of water, sky, sunsets, flowers)
      3. Rejects non-scenic clutter (Screenshots, documents, receipts, flat noise, indoor junk)
    """

    def __init__(self):
        self.face_cascade = None
        self.profile_cascade = None
        self._init_models()

    def _init_models(self):
        if not OPENCV_AVAILABLE:
            return
        try:
            haar_dir = getattr(cv2, "data", None)
            if haar_dir and hasattr(haar_dir, "haarcascades"):
                base_dir = haar_dir.haarcascades
                frontal_path = os.path.join(base_dir, "haarcascade_frontalface_default.xml")
                profile_path = os.path.join(base_dir, "haarcascade_profileface.xml")

                if os.path.exists(frontal_path):
                    self.face_cascade = cv2.CascadeClassifier(frontal_path)
                if os.path.exists(profile_path):
                    self.profile_cascade = cv2.CascadeClassifier(profile_path)

                logger.info("VisionCurator initialized with OpenCV Haar face detection cascades.")
        except Exception as e:
            logger.warning(f"Could not load Haar cascades: {e}")

    def classify(self, img_input: Union[Image.Image, bytes, "np.ndarray"]) -> Dict[str, Any]:
        """
        Classifies an image into:
          - 'portrait': One or more human faces detected.
          - 'nature': Landscapes, greenery, sky, water, sunsets, flora.
          - 'other': Screenshots, receipts, documents, indoor clutter.

        Returns structured dict with category, curated flag, confidence, and tags.
        """
        if not OPENCV_AVAILABLE:
            # Fallback if OpenCV not installed
            return {
                "category": "nature",
                "curated": True,
                "confidence": 0.50,
                "face_count": 0,
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
                    "nature_score": 0.0,
                    "subtype": "invalid",
                    "tags": ["invalid"],
                    "reason": "Failed to decode image data"
                }

            # Resize to standardized analysis resolution (320x240) for constant speed and thresholds
            h, w = bgr.shape[:2]
            analysis_img = cv2.resize(bgr, (320, 240), interpolation=cv2.INTER_AREA)

            # 2. Stage 1: Face Detection (Portraits)
            portrait_res = self._detect_faces(analysis_img)
            if portrait_res is not None:
                return portrait_res

            # 3. Stage 2: Reject Documents & Screenshots
            doc_res = self._detect_document_or_screenshot(analysis_img, orig_w=w, orig_h=h)
            if doc_res is not None:
                return doc_res

            # 4. Stage 3: Nature & Scenic Landscape Detection
            nature_res = self._detect_nature_scene(analysis_img)
            return nature_res

        except Exception as e:
            logger.error(f"Error classifying image: {e}")
            return {
                "category": "other",
                "curated": False,
                "confidence": 0.30,
                "face_count": 0,
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

    def _detect_faces(self, bgr: "np.ndarray") -> Optional[Dict[str, Any]]:
        """Detects human faces using Haar Cascades. Returns portrait dict if faces found."""
        if self.face_cascade is None:
            return None

        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        # Contrast adjustment for face detection in poor lighting
        gray = cv2.equalizeHist(gray)

        # Detect frontal faces
        faces = self.face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=4,
            minSize=(26, 26)
        )

        face_list = list(faces)

        # If no frontal faces, check profile faces
        if len(face_list) == 0 and self.profile_cascade is not None:
            profiles = self.profile_cascade.detectMultiScale(
                gray,
                scaleFactor=1.15,
                minNeighbors=4,
                minSize=(26, 26)
            )
            face_list.extend(list(profiles))
            # Also check horizontally flipped profile
            if len(face_list) == 0:
                flipped = cv2.flip(gray, 1)
                flipped_profiles = self.profile_cascade.detectMultiScale(
                    flipped,
                    scaleFactor=1.15,
                    minNeighbors=4,
                    minSize=(26, 26)
                )
                face_list.extend(list(flipped_profiles))

        if len(face_list) > 0:
            face_count = len(face_list)
            total_img_area = bgr.shape[0] * bgr.shape[1] # 320 * 240 = 76,800

            max_face_area = max(w * h for (x, y, w, h) in face_list)
            face_area_pct = max_face_area / float(total_img_area)

            if face_count >= 3:
                subtype = "group_portrait"
                tag_label = "Group Portrait"
            elif face_area_pct >= 0.12:
                subtype = "close_up"
                tag_label = "Close-up Portrait"
            else:
                subtype = "portrait"
                tag_label = "Portrait"

            confidence = min(0.99, 0.80 + (0.05 * min(3, face_count)) + (0.10 * min(1.0, face_area_pct * 5)))

            return {
                "category": "portrait",
                "curated": True,
                "confidence": round(confidence, 2),
                "face_count": face_count,
                "nature_score": 0.05,
                "subtype": subtype,
                "tags": ["portrait", tag_label, f"{face_count} face{'s' if face_count > 1 else ''}"],
                "reason": f"Detected {face_count} human face(s)"
            }

        return None

    def _detect_document_or_screenshot(self, bgr: "np.ndarray", orig_w: int = 320, orig_h: int = 240) -> Optional[Dict[str, Any]]:
        """Identifies text screenshots, white paper documents, receipts, and flat UI."""
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        sat = hsv[:, :, 1]
        val = hsv[:, :, 2]
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

        total_pixels = bgr.shape[0] * bgr.shape[1]

        # 1. Background Uniformity (Peak histogram ratio)
        hist, _ = np.histogram(gray, bins=32, range=(0, 256))
        max_bin_ratio = np.max(hist) / float(total_pixels)
        dominant_val = np.argmax(hist) * 8

        # White document / receipt background (dominant value > 210 with >= 35% pixels)
        is_white_doc = (dominant_val >= 200 and max_bin_ratio >= 0.35)

        # Dark mode screenshot (dominant value < 35 with >= 40% pixels)
        is_dark_screen = (dominant_val <= 35 and max_bin_ratio >= 0.40)

        # 2. Text Edge Characteristics (Horizontal vs Vertical gradients)
        grad_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        grad_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        edge_energy_x = np.mean(np.abs(grad_x))
        edge_energy_y = np.mean(np.abs(grad_y))

        mean_sat = np.mean(sat) / 255.0

        # Aspect ratio check (common mobile screenshot ratios ~9:16 = 0.56 or ~19.5:9 = 0.46)
        aspect_ratio = min(orig_w, orig_h) / max(orig_w, orig_h)
        is_phone_aspect = (aspect_ratio <= 0.60)

        # Classification rules for document / screenshot
        if (is_white_doc or is_dark_screen) and mean_sat < 0.15:
            return {
                "category": "other",
                "curated": False,
                "confidence": 0.92,
                "face_count": 0,
                "nature_score": 0.02,
                "subtype": "document",
                "tags": ["other", "Document / Text"],
                "reason": "Dominant flat background with low color saturation"
            }

        if is_phone_aspect and max_bin_ratio >= 0.30 and mean_sat < 0.20:
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

        # Monochromatic text with very low saturation (< 0.08) and high text edges
        if mean_sat < 0.08 and edge_energy_x > 18.0:
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
        """Analyzes color palettes and spatial layout for landscapes and nature."""
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        H = hsv[:, :, 0] # 0..180
        S = hsv[:, :, 1] # 0..255
        V = hsv[:, :, 2] # 0..255

        total_pixels = float(bgr.shape[0] * bgr.shape[1])

        # 1. Foliage / Greenery (Hue 35..85, moderate saturation and value)
        foliage_mask = (H >= 35) & (H <= 85) & (S >= 40) & (V >= 35)
        foliage_ratio = np.count_nonzero(foliage_mask) / total_pixels

        # 2. Sky & Water Blue (Hue 90..130, value > 60)
        sky_water_mask = (H >= 90) & (H <= 130) & (S >= 25) & (V >= 55)
        sky_water_ratio = np.count_nonzero(sky_water_mask) / total_pixels

        # 3. Sunset / Golden Hour / Warm Earth (Hue 0..22 or 165..180, high saturation)
        sunset_mask = ((H <= 22) | (H >= 165)) & (S >= 75) & (V >= 60)
        sunset_ratio = np.count_nonzero(sunset_mask) / total_pixels

        # 4. Floral Vibrant Blooms (Pink, Magenta, Yellow, Purple)
        floral_mask = ((H >= 140) & (H <= 165) & (S >= 85)) | ((H >= 22) & (H <= 35) & (S >= 95))
        floral_ratio = np.count_nonzero(floral_mask) / total_pixels

        # 5. Hasler & Süsstrunk Colorfulness Metric
        colorfulness = self._calc_colorfulness(bgr)
        norm_colorfulness = min(0.20, colorfulness / 200.0)

        # 6. Spatial Composition Heuristic: Sky at top, Earth/Vegetation at bottom
        top_half_hsv = hsv[:120, :, :]
        bot_half_hsv = hsv[120:, :, :]
        top_pixels = 120.0 * 320.0

        top_sky = np.count_nonzero((top_half_hsv[:,:,0] >= 90) & (top_half_hsv[:,:,0] <= 130) & (top_half_hsv[:,:,2] >= 60)) / top_pixels
        bot_green = np.count_nonzero((bot_half_hsv[:,:,0] >= 35) & (bot_half_hsv[:,:,0] <= 85) & (bot_half_hsv[:,:,1] >= 40)) / top_pixels

        spatial_bonus = 0.0
        if top_sky >= 0.25 and bot_green >= 0.20:
            spatial_bonus = 0.18 # Definite horizon landscape
        elif top_sky >= 0.35:
            spatial_bonus = 0.12 # Open sky landscape
        elif bot_green >= 0.35:
            spatial_bonus = 0.12 # Forest / ground scenery

        # Total Nature Score
        nature_score = (
            (foliage_ratio * 1.5) +
            (sky_water_ratio * 1.3) +
            (sunset_ratio * 1.3) +
            (floral_ratio * 1.8) +
            norm_colorfulness +
            spatial_bonus
        )

        # Threshold evaluation
        is_nature = (
            nature_score >= 0.20 or
            foliage_ratio >= 0.14 or
            sky_water_ratio >= 0.18 or
            sunset_ratio >= 0.16 or
            floral_ratio >= 0.08
        )

        if is_nature:
            # Determine dominant natural subtype
            scores = {
                "foliage": foliage_ratio * 1.5,
                "water_beach": sky_water_ratio * 1.3,
                "sky_sunset": sunset_ratio * 1.3,
                "flowers": floral_ratio * 1.8,
                "landscape": spatial_bonus * 1.2
            }
            top_subtype = max(scores, key=scores.get)

            labels = {
                "foliage": "Greenery & Foliage",
                "water_beach": "Ocean & Water",
                "sky_sunset": "Sunset & Sky",
                "flowers": "Floral & Blooms",
                "landscape": "Scenic Landscape"
            }
            tag_label = labels.get(top_subtype, "Nature Scenery")
            confidence = min(0.98, max(0.65, nature_score * 1.8))

            return {
                "category": "nature",
                "curated": True,
                "confidence": round(confidence, 2),
                "face_count": 0,
                "nature_score": round(nature_score, 3),
                "subtype": top_subtype,
                "tags": ["nature", tag_label],
                "reason": f"High natural scenery indicators (Foliage: {foliage_ratio:.0%}, Sky/Water: {sky_water_ratio:.0%}, Warm: {sunset_ratio:.0%})"
            }

        # Otherwise: Indoor, cluttered, or ambiguous
        return {
            "category": "other",
            "curated": False,
            "confidence": round(1.0 - min(0.8, nature_score), 2),
            "face_count": 0,
            "nature_score": round(nature_score, 3),
            "subtype": "indoor_or_clutter",
            "tags": ["other", "Indoor / Clutter"],
            "reason": "Insufficient portrait or natural scenery scores"
        }

    @staticmethod
    def _calc_colorfulness(bgr: "np.ndarray") -> float:
        """Computes Hasler & Süsstrunk natural colorfulness metric."""
        try:
            B = bgr[:, :, 0].astype(float)
            G = bgr[:, :, 1].astype(float)
            R = bgr[:, :, 2].astype(float)

            rg = np.abs(R - G)
            yb = np.abs(0.5 * (R + G) - B)

            std_rg = np.std(rg)
            mean_rg = np.mean(rg)

            std_yb = np.std(yb)
            mean_yb = np.mean(yb)

            std_rgyb = np.sqrt(std_rg ** 2 + std_yb ** 2)
            mean_rgyb = np.sqrt(mean_rg ** 2 + mean_yb ** 2)

            return float(std_rgyb + 0.3 * mean_rgyb)
        except Exception:
            return 0.0
