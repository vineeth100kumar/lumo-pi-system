import logging
import datetime
import pytz
from config import HOUR_SLEEP_START, HOUR_SLEEP_END, HOUR_DROWSY_START

logger = logging.getLogger("EmotionEngine")

class EmotionEngine:
    def __init__(self):
        self.tz = pytz.timezone("Asia/Kolkata")
        self.current_mood = "NORMAL"
        self.current_schedule = "AWAKE"

    def get_schedule(self) -> str:
        h = datetime.datetime.now(self.tz).hour
        if HOUR_SLEEP_START <= h < HOUR_SLEEP_END:
            return "SLEEP"
        if h >= HOUR_DROWSY_START:
            return "DROWSY"
        return "AWAKE"

    async def push_schedule(self, hub, mood: str = None) -> None:
        if not hub.connected: return
        schedule = self.get_schedule()
        if mood:
            self.current_mood = mood

        if schedule != self.current_schedule or mood:
            self.current_schedule = schedule
            await hub.send_json({
                "cmd": "EMOTION",
                "mood": self.current_mood,
                "schedule": schedule
            })
            logger.info(f"Emotion updated: mood={self.current_mood}, schedule={schedule}")

    async def on_spotify_playing(self, hub):
        await self.push_schedule(hub, "HAPPY")

    async def on_spotify_paused(self, hub):
        await self.push_schedule(hub, "NORMAL")

    async def on_alarm_dismissed(self, hub):
        await self.push_schedule(hub, "HAPPY")
