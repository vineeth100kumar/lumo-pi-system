import asyncio
import random
import logging
from typing import Optional

logger = logging.getLogger("AnimationEngine")

COLOR_PRESETS = {
    "cyan":   {"hex": "#00F0FF", "r": 0,   "g": 240, "b": 255, "rgb565": 0x077F},
    "pink":   {"hex": "#FF3399", "r": 255, "g": 51,  "b": 153, "rgb565": 0xF9B3},
    "green":  {"hex": "#00FF88", "r": 0,   "g": 255, "b": 136, "rgb565": 0x07F1},
    "gold":   {"hex": "#FFCC00", "r": 255, "g": 204, "b": 0,   "rgb565": 0xFE60},
    "purple": {"hex": "#B040FF", "r": 176, "g": 64,  "b": 255, "rgb565": 0xB21F},
    "white":  {"hex": "#FFFFFF", "r": 255, "g": 255, "b": 255, "rgb565": 0xFFFF},
}

class AnimationEngine:
    def __init__(self):
        self.current_anim = "normal"
        self.current_color = "cyan"
        self.gaze_x = 0
        self.gaze_y = 0
        self.music_playing = False
        self.one_shot_active = False

    def get_color_rgb565(self, name: str) -> int:
        preset = COLOR_PRESETS.get(name.lower(), COLOR_PRESETS["cyan"])
        return preset["rgb565"]

    async def set_eye_color(self, color_name: str, hub) -> bool:
        color_name = color_name.lower()
        if color_name in COLOR_PRESETS:
            self.current_color = color_name
            rgb565 = COLOR_PRESETS[color_name]["rgb565"]
            await hub.send_json({
                "cmd": "EYE_COLOR",
                "name": color_name,
                "rgb565": rgb565
            })
            logger.info(f"Eye color changed to {color_name} (0x{rgb565:04X})")
            return True
        return False

    async def play_animation(self, anim_name: str, hub, duration: float = 2.5):
        """Triggers an expressive one-shot animation from the Pi."""
        self.current_anim = anim_name.lower()
        self.one_shot_active = True
        logger.info(f"Playing animation: {self.current_anim} for {duration}s")

        await hub.send_json({
            "cmd": "ANIM",
            "type": self.current_anim,
            "duration_ms": int(duration * 1000)
        })

        if duration > 0:
            async def revert():
                await asyncio.sleep(duration)
                self.one_shot_active = False
                self.current_anim = "normal"
                await hub.send_json({"cmd": "ANIM", "type": "normal", "duration_ms": 0})

            asyncio.create_task(revert())

    async def poll_idle(self, hub, current_screen: str, is_music_active: bool):
        """Called every 2 seconds by APScheduler to generate organic life-like micro-movements."""
        if current_screen != "FACE" or self.one_shot_active:
            return

        # If music is playing, dance!
        if is_music_active:
            bounce_y = random.choice([-8, -14, -6, 0])
            bounce_x = random.choice([-5, 5, 0])
            await hub.send_json({
                "cmd": "ANIM",
                "type": "music_dance",
                "gaze_x": bounce_x,
                "gaze_y": bounce_y,
                "duration_ms": 600
            })
            return

        # Organic idle gaze shifts (saccades)
        dice = random.random()
        if dice < 0.35:
            # Look somewhere with smooth gaze
            self.gaze_x = random.choice([-15, -8, 0, 8, 15])
            self.gaze_y = random.choice([-6, 0, 6])
            await hub.send_json({
                "cmd": "ANIM",
                "type": "look",
                "gaze_x": self.gaze_x,
                "gaze_y": self.gaze_y,
                "duration_ms": 1200
            })
        elif dice < 0.45:
            # Organic double-blink or quick wink
            action = random.choice(["double_blink", "wink_left", "wink_right"])
            await hub.send_json({
                "cmd": "ANIM",
                "type": action,
                "duration_ms": 600
            })
        elif dice < 0.52:
            # Curious tilt
            await hub.send_json({
                "cmd": "ANIM",
                "type": "curious",
                "duration_ms": 1500
            })
