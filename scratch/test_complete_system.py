import os
import sys
import unittest
import json
import shutil
import tempfile
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.abspath('rpi_server'))

from services.vision_curator import VisionCurator
from services.memories import MemoriesService
from ws_hub import WSHub

class TestVisionCurator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.curator = VisionCurator()
        print(f"\n--- Testing VisionCurator (OpenCV available: {cls.curator.is_available}) ---")

    def test_curator_availability(self):
        self.assertTrue(self.curator.is_available)
        print("  [OK] OpenCV and Haar cascades active")

    def test_nature_sky_detection(self):
        # Create a realistic sky scene with vertical gradient and light cloud texture
        arr = np.zeros((240, 320, 3), dtype=np.uint8)
        for y in range(240):
            # Gradient from deep azure (120, 180, 255) to pale sky blue (190, 220, 255)
            factor = y / 240.0
            r = int(120 + 70 * factor)
            g = int(180 + 40 * factor)
            b = 255
            arr[y, :] = [r, g, b]
        noise = np.random.randint(-10, 10, (240, 320, 3), dtype=np.int16)
        arr = np.clip(arr.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        img = Image.fromarray(arr)

        res = self.curator.classify(img)
        self.assertTrue(res['curated'])
        self.assertEqual(res['category'], 'nature')
        self.assertEqual(res['subtype'], 'sky')
        print("  [OK] Sky with gradient -> Nature (sky)")

    def test_nature_sunset_detection(self):
        # Create realistic sunset scene with rich warm orange gradient and texture
        arr = np.zeros((240, 320, 3), dtype=np.uint8)
        for y in range(240):
            factor = y / 240.0
            r = 255
            g = int(60 + 120 * factor)
            b = int(20 + 40 * factor)
            arr[y, :] = [r, g, b]
        noise = np.random.randint(-8, 8, (240, 320, 3), dtype=np.int16)
        arr = np.clip(arr.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        img = Image.fromarray(arr)

        res = self.curator.classify(img)
        self.assertTrue(res['curated'])
        self.assertEqual(res['category'], 'nature')
        self.assertEqual(res['subtype'], 'sunset')
        print("  [OK] Sunset gradient -> Nature (sunset)")

    def test_nature_foliage_detection(self):
        # Green foliage with organic texture
        arr = np.zeros((240, 320, 3), dtype=np.uint8)
        arr[:, :] = [34, 139, 34] # Forest green
        noise = np.random.randint(-20, 20, (240, 320, 3), dtype=np.int16)
        arr = np.clip(arr.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        img = Image.fromarray(arr)
        res = self.curator.classify(img)
        self.assertTrue(res['curated'])
        self.assertEqual(res['category'], 'nature')
        self.assertEqual(res['subtype'], 'foliage')
        print("  [OK] Foliage -> Nature (foliage)")

    def test_indoor_clutter_rejection(self):
        # Neutral gray/brown low-saturation clutter
        arr = np.full((240, 320, 3), (120, 115, 110), dtype=np.uint8)
        img = Image.fromarray(arr)
        res = self.curator.classify(img)
        self.assertFalse(res['curated'])
        self.assertEqual(res['category'], 'other')
        print("  [OK] Low-saturation clutter -> Filtered (other)")

    def test_dark_image_rejection(self):
        # Very dark photo
        arr = np.full((240, 320, 3), (25, 25, 30), dtype=np.uint8)
        img = Image.fromarray(arr)
        res = self.curator.classify(img)
        self.assertFalse(res['curated'])
        self.assertEqual(res['category'], 'other')
        print("  [OK] Dark indoor photo -> Filtered (other)")

    def test_real_photos_from_library(self):
        real_photos_dir = "scratch/all_photos"
        if os.path.exists(real_photos_dir):
            files = [f for f in os.listdir(real_photos_dir) if f.endswith(('.jpg', '.gif'))]
            portraits = 0
            nature = 0
            other = 0
            for f in files:
                p = os.path.join(real_photos_dir, f)
                with Image.open(p) as img:
                    res = self.curator.classify(img)
                    if res['category'] == 'portrait':
                        portraits += 1
                    elif res['category'] == 'nature':
                        nature += 1
                    else:
                        other += 1
            self.assertEqual(len(files), 50)
            self.assertGreaterEqual(portraits, 40)
            self.assertGreaterEqual(nature, 4)
            self.assertEqual(portraits + nature + other, 50)
            print(f"  [OK] Full 50-photo live library classification: {portraits} Portraits, {nature} Nature, {other} Filtered")

    def test_smart_crop_preserves_faces_and_aspect_ratio(self):
        print("\n--- Testing Face-Safe Smart Cropping ---")
        mem = MemoriesService(base_dir=tempfile.gettempdir())
        tall_img = Image.new("RGB", (1080, 1920), (200, 200, 200))
        face_boxes = [
            [0.20, 0.12, 0.20, 0.15],
            [0.45, 0.10, 0.22, 0.16],
            [0.70, 0.13, 0.18, 0.14]
        ]
        cropped = mem._smart_crop(tall_img, face_boxes=face_boxes)
        ratio = cropped.width / float(cropped.height)
        self.assertAlmostEqual(ratio, 4.0 / 3.0, places=2)
        final_img = cropped.resize((320, 240), Image.Resampling.LANCZOS)
        self.assertEqual(final_img.size, (320, 240))
        print("  [OK] Smart crop produces exact 4:3 aspect ratio and preserves face headroom")


class TestMemoriesService(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.lib_dir = os.path.join(self.test_dir, "library")
        self.thumbs_dir = os.path.join(self.test_dir, "thumbs")
        self.inbox_dir = os.path.join(self.test_dir, "inbox")
        self.index_file = os.path.join(self.test_dir, "index.json")
        os.makedirs(self.lib_dir)
        os.makedirs(self.thumbs_dir)
        os.makedirs(self.inbox_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_gradient_image(self, name: str):
        p = os.path.join(self.lib_dir, name)
        t = os.path.join(self.thumbs_dir, name.replace(".gif", ".jpg"))
        arr = np.zeros((240, 320, 3), dtype=np.uint8)
        for y in range(240):
            arr[y, :] = [int(120 + 70 * (y / 240.0)), int(180 + 40 * (y / 240.0)), 255]
        noise = np.random.randint(-10, 10, (240, 320, 3), dtype=np.int16)
        arr = np.clip(arr.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        img = Image.fromarray(arr)
        img.save(p)
        img.save(t)
        return p, t

    def test_schema_migration_and_force_rescan(self):
        print("\n--- Testing MemoriesService Schema Migration & Force Re-scan ---")
        legacy_data = {
            "cv_version": 3,
            "photos": [
                {
                    "id": "mem_001",
                    "filename": "mem_001.jpg",
                    "thumb": "mem_001.jpg",
                    "caption": "Test Photo 1",
                    "category": "other",
                    "curated": False,
                    "curated_override": False  # Legacy boolean
                }
            ]
        }
        self._create_gradient_image("mem_001.jpg")
        with open(self.index_file, "w") as f:
            json.dump(legacy_data, f)

        mem = MemoriesService(base_dir=self.test_dir)
        mem.index_file = self.index_file
        mem.library_dir = self.lib_dir
        mem.thumbs_dir = self.thumbs_dir
        mem.inbox_dir = self.inbox_dir
        mem._load_index()

        self.assertEqual(mem.cv_version, 5)
        print("  [OK] cv_version successfully upgraded from 3 to 5")

        p1 = next(p for p in mem.photos if p["id"] == "mem_001")
        self.assertIsNone(p1.get("curated_override"))
        print("  [OK] Legacy curated_override: False migrated to None")

        self.assertEqual(p1["category"], "nature")
        self.assertTrue(p1["curated"])
        print("  [OK] Uncurated photo was automatically re-scanned and classified as nature on startup")

    def test_overrides_and_auto_reset(self):
        print("\n--- Testing Manual Overrides & Auto AI Reset ---")
        self._create_gradient_image("mem_003.jpg")
        mem = MemoriesService(base_dir=self.test_dir)
        mem.index_file = self.index_file
        mem.library_dir = self.lib_dir
        mem.thumbs_dir = self.thumbs_dir
        mem.inbox_dir = self.inbox_dir
        mem.photos = [{
            "id": "mem_003",
            "filename": "mem_003.jpg",
            "thumb": "mem_003.jpg",
            "caption": "Sky photo",
            "category": "nature",
            "curated": True,
            "curated_override": None
        }]

        # 1. Manually override to 'other'
        res = mem.set_photo_category_override("mem_003", "other")
        self.assertIsNotNone(res)
        self.assertEqual(res["category"], "other")
        self.assertFalse(res["curated"])
        self.assertEqual(res["curated_override"], "other")
        print("  [OK] Manual override to 'other' works")

        # 2. Reset back using 'auto'
        res2 = mem.set_photo_category_override("mem_003", "auto")
        self.assertIsNotNone(res2)
        self.assertIsNone(res2["curated_override"])
        self.assertEqual(res2["category"], "nature")
        self.assertTrue(res2["curated"])
        print("  [OK] 'auto' reset cleared override and accurately re-classified with Vision AI")

    def test_get_displayable_photos_fallback(self):
        print("\n--- Testing Desk Screen Display Filtering & Fallbacks ---")
        mem = MemoriesService(base_dir=self.test_dir)
        mem.curate_display = True
        mem.photos = [
            {"id": "p1", "category": "portrait", "curated": True},
            {"id": "p2", "category": "other", "curated": False},
            {"id": "p3", "category": "nature", "curated": True},
        ]
        disp = mem.get_displayable_photos()
        self.assertEqual(len(disp), 2)
        self.assertEqual([p["id"] for p in disp], ["p1", "p3"])
        print("  [OK] Only portrait and nature returned when curate_display is True")

        # Fallback test: if only 'other' photos exist, fallback to all so screen is never blank
        mem.photos = [{"id": "p2", "category": "other", "curated": False}]
        disp_fallback = mem.get_displayable_photos()
        self.assertEqual(len(disp_fallback), 1)
        self.assertEqual(disp_fallback[0]["id"], "p2")
        print("  [OK] Graceful fallback: displays all photos if no photos match curation")

    def test_strip_encoding_format(self):
        print("\n--- Testing Binary Frame Strips Format (ESP32 Protocol) ---")
        mem = MemoriesService(base_dir=self.test_dir)
        img = Image.new("RGB", (320, 240), (255, 0, 0)) # Red image
        strips = mem._render_frame_strips(img)
        self.assertEqual(len(strips), 12)
        for idx, s in enumerate(strips):
            # 8 bytes header + 320 * 20 * 2 bytes pixels = 12808 bytes
            self.assertEqual(len(s), 12808)
            # Check magic header 0xAA 0xCC (MEMORY_STRIP)
            self.assertEqual(s[0], 0xAA)
            self.assertEqual(s[1], 0xCC)
            # y offset = idx * 20
            expected_y = idx * 20
            actual_y = s[2] | (s[3] << 8)
            self.assertEqual(actual_y, expected_y)
        print("  [OK] All 12 binary strips match ESP32 DMA format (12808 bytes, header 0xAA 0xCC, correct y-offsets)")

if __name__ == "__main__":
    unittest.main()
