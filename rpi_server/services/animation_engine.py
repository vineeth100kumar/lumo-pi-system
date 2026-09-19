import asyncio
import random
import logging
from typing import Optional

logger = logging.getLogger("AnimationEngine")

COLOR_PRESETS = {
    "cyan":   {"hex": "#00E5FF", "r": 0,   "g": 229, "b": 255, "rgb565": 0x073F},
    "amber":  {"hex": "#FFB300", "r": 255, "g": 179, "b": 0,   "rgb565": 0xFD60},
    "green":  {"hex": "#00FF66", "r": 0,   "g": 255, "b": 102, "rgb565": 0x07E6},
    "white":  {"hex": "#E0F7FA", "r": 224, "g": 247, "b": 250, "rgb565": 0xF7BE},
    "purple": {"hex": "#9D00FF", "r": 157, "g": 0,   "b": 255, "rgb565": 0x981F},
    "red":    {"hex": "#FF1744", "r": 255, "g": 23,  "b": 68,  "rgb565": 0xF8A4},
}

class AnimationEngine:
    def __init__(self):
        self.current_anim = "normal"
        self.current_color = "cyan"
        self.gaze_x = 0
        self.gaze_y = 0
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
            logger.info(f"Cybernetic Eye Color changed to {color_name} (0x{rgb565:04X})")
            return True
        return False

    async def play_animation(self, anim_name: str, hub, duration: float = 2.5):
        """Triggers a high-tech robotic expression from the Pi."""
        self.current_anim = anim_name.lower()
        self.one_shot_active = True
        logger.info(f"Playing Cybernetic Animation: {self.current_anim} for {duration}s")

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

        # If music is playing, activate audio beat groove!
        if is_music_active:
            bounce_y = random.choice([-6, -10, -4, 0])
            bounce_x = random.choice([-4, 4, 0])
            await hub.send_json({
                "cmd": "ANIM",
                "type": "dance",
                "gaze_x": bounce_x,
                "gaze_y": bounce_y,
                "duration_ms": 600
            })
            return

        # Organic idle gaze shifts (saccades)
        dice = random.random()
        if dice < 0.35:
            # Look somewhere with sharp micro-glance
            self.gaze_x = random.choice([-16, -8, 0, 8, 16])
            self.gaze_y = random.choice([-6, 0, 6])
            await hub.send_json({
                "cmd": "ANIM",
                "type": "look",
                "gaze_x": self.gaze_x,
                "gaze_y": self.gaze_y,
                "duration_ms": 1400
            })
        elif dice < 0.45:
            # Subtle determined focus
            await hub.send_json({
                "cmd": "ANIM",
                "type": "focused",
                "duration_ms": 1600
            })
        elif dice < 0.52:
            # Quick curious scan
            await hub.send_json({
                "cmd": "ANIM",
                "type": "curious",
                "duration_ms": 1400
            })
