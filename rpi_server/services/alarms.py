"""
Alarms, kept in Sage alongside everything else.

An alarm here is a Sage reminder tagged `alarm`: the time it should ring is its
`remind_at`, the time it is set for is its `start_at`, and turning it off
clears the reminder while leaving the time. That means an alarm set at the desk
clock shows up on the phone, and a reminder set on the phone can ring the
buzzer, without either project knowing anything about the other's code.

Lumo still watches the clock itself rather than waiting for Sage's minute-long
reminder sweep, because an alarm that goes off up to a minute late is not an
alarm. Sage's own event for the same item arrives shortly after and is ignored.
"""

import datetime
import logging
from typing import Optional

from config import SAGE_ALARM_TAG
from services.sage_client import now_local

logger = logging.getLogger("AlarmManager")

# An alarm whose time passed while the Pi was off should ring tomorrow, not the
# moment the power comes back. Anything older than this is rolled forward.
GRACE_SECONDS = 300


def _parse(value: Optional[str]) -> Optional[datetime.datetime]:
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def next_occurrence(hour: int, minute: int, after: Optional[datetime.datetime] = None) -> datetime.datetime:
    """The next time today or tomorrow that the clock reads hour:minute."""
    base = after or now_local()
    candidate = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= base:
        candidate += datetime.timedelta(days=1)
    return candidate


class Alarm:
    """A Sage reminder, read as an alarm."""

    def __init__(self, item: dict):
        self.item = item
        self.id: str = item.get("id", "")
        self.label: str = item.get("title") or "Alarm"
        self.set_for = _parse(item.get("start_at"))
        self.rings_at = _parse(item.get("remind_at"))

    @property
    def enabled(self) -> bool:
        return self.rings_at is not None

    @property
    def h(self) -> int:
        return self.set_for.hour if self.set_for else 0

    @property
    def m(self) -> int:
        return self.set_for.minute if self.set_for else 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "h": self.h,
            "m": self.m,
            "enabled": self.enabled,
            "label": self.label,
        }


class AlarmManager:
    def __init__(self, sage):
        self.sage = sage
        self.alarms: list[Alarm] = []
        self.ringing_id: Optional[str] = None
        # Items already rung, so neither a second poll nor Sage's own reminder
        # event sounds the same alarm twice.
        self._fired: set[str] = set()

    def _find(self, alarm_id: str) -> Optional[Alarm]:
        return next((a for a in self.alarms if a.id == alarm_id), None)

    async def _load(self) -> bool:
        """Read the alarms out of Sage. False when Sage could not be reached."""
        rows = await self.sage.list_items(entity_type="reminder", completed_within_days=1)
        if not rows and not self.sage.online:
            return False

        tag = SAGE_ALARM_TAG.lower()
        alarms = []
        for row in rows:
            if row.get("is_completed"):
                continue
            tags = [t.strip().lower() for t in (row.get("context_tags") or "").split(",")]
            if tag in tags:
                alarms.append(Alarm(row))
        self.alarms = sorted(alarms, key=lambda a: (a.h, a.m))
        self._fired &= {a.id for a in self.alarms}
        return True

    async def refresh(self) -> list[Alarm]:
        """
        Re-read the alarms from Sage and roll any missed ones forward.

        An alarm whose time passed while the Pi was off would otherwise sit
        permanently overdue, so it is moved to its next occurrence instead.
        """
        if not await self._load():
            return self.alarms

        now = now_local()
        missed = [
            a for a in self.alarms
            if a.rings_at
            and a.id not in self._fired
            and (now - a.rings_at).total_seconds() > GRACE_SECONDS
        ]
        if not missed:
            return self.alarms

        for alarm in missed:
            logger.info(f"Alarm {alarm.id} was missed; moving it to its next occurrence")
            await self.sage.update_item(alarm.id, {
                "start_at": next_occurrence(alarm.h, alarm.m).isoformat(),
                "remind_at": next_occurrence(alarm.h, alarm.m).isoformat(),
            })
        await self._load()
        return self.alarms

    async def _set_time(self, alarm: Alarm, when: Optional[datetime.datetime], move_set_for: bool = True) -> bool:
        """
        Point an alarm at a new time.

        `when` of None turns it off: Sage only sends a reminder for an item
        that has one, so clearing `remind_at` is what "disabled" means, and
        `start_at` keeps the time so it can be switched back on.
        """
        payload: dict = {"remind_at": when.isoformat() if when else None}
        if when and move_set_for:
            payload["start_at"] = when.isoformat()
        updated = await self.sage.update_item(alarm.id, payload)
        if updated is None:
            return False
        self._fired.discard(alarm.id)
        await self._load()
        return True

    async def add_alarm(self, h: int, m: int, label: str = "") -> Optional[Alarm]:
        rings_at = next_occurrence(h, m)
        payload = {
            "title": label.strip() or f"Alarm {h:02d}:{m:02d}",
            # Written here so Sage's description worker leaves an alarm alone.
            "description": "Alarm set on Lumo.",
            "entity_type": "reminder",
            "priority": "high",
            "start_at": rings_at.isoformat(),
            "remind_at": rings_at.isoformat(),
            "due_date": rings_at.strftime("%Y-%m-%d"),
            "context_tags": SAGE_ALARM_TAG,
        }
        created = await self.sage.create_item(payload)
        if created is None:
            logger.error(f"Could not create alarm {h:02d}:{m:02d} in Sage")
            return None
        logger.info(f"Added alarm {h:02d}:{m:02d} ({label}) as Sage reminder {created.get('id')}")
        await self.refresh()
        return self._find(created.get("id", "")) or Alarm(created)

    async def delete_alarm(self, alarm_id: str) -> bool:
        if self.ringing_id == alarm_id:
            self.ringing_id = None
        if not await self.sage.delete_item(alarm_id):
            return False
        logger.info(f"Deleted alarm {alarm_id}")
        await self.refresh()
        return True

    async def toggle_alarm(self, alarm_id: str) -> bool:
        alarm = self._find(alarm_id)
        if not alarm:
            return False
        if alarm.enabled:
            logger.info(f"Disabled alarm {alarm_id}")
            return await self._set_time(alarm, None)
        logger.info(f"Enabled alarm {alarm_id}")
        return await self._set_time(alarm, next_occurrence(alarm.h, alarm.m))

    async def snooze(self) -> bool:
        """
        Five more minutes, without moving the alarm itself.

        Only `remind_at` shifts, so tomorrow's alarm is still set for the time
        it has always been set for rather than creeping later every morning.
        """
        alarm = self._find(self.ringing_id or "")
        self.ringing_id = None
        if not alarm:
            return False
        later = now_local() + datetime.timedelta(minutes=5)
        logger.info(f"Snoozed alarm {alarm.id} to {later.strftime('%H:%M')}")
        return await self._set_time(alarm, later, move_set_for=False)

    async def dismiss(self) -> bool:
        """Stop the alarm and set it for the same time tomorrow."""
        alarm = self._find(self.ringing_id or "")
        self.ringing_id = None
        if not alarm:
            return False
        logger.info(f"Dismissed alarm {alarm.id}")
        return await self._set_time(alarm, next_occurrence(alarm.h, alarm.m))

    def mark_fired(self, item_id: str) -> bool:
        """Record that an item has rung. False if it already had."""
        if item_id in self._fired:
            return False
        self._fired.add(item_id)
        return True

    async def poll(self, hub) -> None:
        """Ring anything that has come due since the last look."""
        if self.ringing_id is not None:
            return
        now = now_local()
        for alarm in self.alarms:
            if not alarm.enabled or alarm.id in self._fired:
                continue
            overdue = (now - alarm.rings_at).total_seconds()
            if 0 <= overdue <= GRACE_SECONDS:
                self.mark_fired(alarm.id)
                self.ringing_id = alarm.id
                logger.info(f"ALARM RINGING: {alarm.h:02d}:{alarm.m:02d} - {alarm.label}")
                await hub.send_json({"cmd": "ALARM_RING"})
                return

    def list_alarms(self) -> list:
        return [a.to_dict() for a in self.alarms]

    def get_all(self) -> list:
        """What the voice assistant asks for when it builds its prompt."""
        return self.list_alarms()
