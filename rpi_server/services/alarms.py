import os
import json
import logging
import datetime
import pytz
from config import ALARM_FILE

logger = logging.getLogger("AlarmManager")

class Alarm:
    def __init__(self, id: int, h: int, m: int, enabled: bool = True, label: str = ""):
        self.id = id
        self.h = h
        self.m = m
        self.enabled = enabled
        self.label = label

    def to_dict(self):
        return {
            "id": self.id,
            "h": self.h,
            "m": self.m,
            "enabled": self.enabled,
            "label": self.label
        }

class AlarmManager:
    def __init__(self):
        self.alarms: list[Alarm] = []
        self.ringing_id = None
        self.last_ring_minute = -1
        self.tz = pytz.timezone("Asia/Kolkata")
        self._load()

    def _load(self):
        if os.path.exists(ALARM_FILE):
            try:
                with open(ALARM_FILE, "r") as f:
                    data = json.load(f)
                self.alarms = [Alarm(**item) for item in data]
            except Exception as e:
                logger.error(f"Error loading alarms.json: {e}")
                self.alarms = []
        else:
            # Default alarm 07:30
            self.alarms = [Alarm(1, 7, 30, False, "Morning")]
            self._save()

    def _save(self):
        try:
            with open(ALARM_FILE, "w") as f:
                json.dump([a.to_dict() for a in self.alarms], f, indent=2)
        except Exception as e:
            logger.error(f"Error saving alarms.json: {e}")

    def add_alarm(self, h: int, m: int, label: str = "") -> Alarm:
        new_id = max([a.id for a in self.alarms], default=0) + 1
        alarm = Alarm(new_id, h, m, True, label)
        self.alarms.append(alarm)
        self._save()
        logger.info(f"Added alarm {h:02d}:{m:02d} ({label})")
        return alarm

    def delete_alarm(self, alarm_id: int):
        self.alarms = [a for a in self.alarms if a.id != alarm_id]
        if self.ringing_id == alarm_id:
            self.ringing_id = None
        self._save()
        logger.info(f"Deleted alarm ID {alarm_id}")

    def toggle_alarm(self, alarm_id: int):
        for a in self.alarms:
            if a.id == alarm_id:
                a.enabled = not a.enabled
                logger.info(f"Toggled alarm ID {alarm_id} -> {a.enabled}")
                break
        self._save()

    def snooze(self):
        if self.ringing_id is not None:
            for a in self.alarms:
                if a.id == self.ringing_id:
                    a.m = (a.m + 5) % 60
                    if a.m < 5:
                        a.h = (a.h + 1) % 24
                    logger.info(f"Snoozed alarm to {a.h:02d}:{a.m:02d}")
                    break
            self.ringing_id = None
            self._save()

    def dismiss(self):
        if self.ringing_id is not None:
            for a in self.alarms:
                if a.id == self.ringing_id:
                    a.enabled = False
                    logger.info(f"Dismissed alarm ID {self.ringing_id}")
                    break
            self.ringing_id = None
            self._save()

    async def poll(self, hub) -> None:
        now = datetime.datetime.now(self.tz)
        if now.minute == self.last_ring_minute and self.ringing_id is not None:
            return

        for a in self.alarms:
            if a.enabled and a.h == now.hour and a.m == now.minute:
                if self.ringing_id != a.id:
                    self.ringing_id = a.id
                    self.last_ring_minute = now.minute
                    logger.info(f"ALARM RINGING: {a.h:02d}:{a.m:02d} - {a.label}")
                    await hub.send_json({"cmd": "ALARM_RING"})
                return

        if self.ringing_id is not None and now.minute != self.last_ring_minute:
            self.ringing_id = None

    def list_alarms(self) -> list:
        return [a.to_dict() for a in self.alarms]
