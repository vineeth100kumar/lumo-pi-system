"""
Lumo's view of the task list, which is Sage's task list.

This used to be a list of plain strings in tasks.json, so a task added at the
desk clock was invisible on the phone and vice versa. There is one list now and
Sage keeps it; everything here is a cache of it, refreshed when Sage says
something changed.
"""

import logging
from typing import Optional

from config import SAGE_ALARM_TAG

logger = logging.getLogger("TaskService")

_PRIORITY_ORDER = {"urgent": 0, "high": 1, "medium": 2, "low": 3}


def _sort_key(item: dict) -> tuple:
    """Soonest first, then most urgent. Undated tasks sort after dated ones."""
    due = item.get("due_date") or item.get("start_at") or ""
    return (0 if due else 1, due, _PRIORITY_ORDER.get(item.get("priority"), 2))


class TaskService:
    def __init__(self, sage):
        self.sage = sage
        self.items: list[dict] = []

    async def refresh(self) -> list[dict]:
        """Re-read the open tasks from Sage, keeping the last list on failure."""
        rows = await self.sage.list_items(entity_type="task", completed_within_days=1)
        if not rows and not self.sage.online:
            return self.items
        open_items = [r for r in rows if not r.get("is_completed")]
        self.items = sorted(open_items, key=_sort_key)
        return self.items

    def get_items(self) -> list[dict]:
        return self.items

    def get_tasks(self) -> list[str]:
        return [item.get("title", "") for item in self.items]

    def get_all(self) -> list[str]:
        """What the voice assistant asks for when it builds its prompt."""
        return self.get_tasks()

    async def add_task(self, text: str) -> Optional[dict]:
        """
        Add a task by writing it the way a person says it.

        Sage's capture engine reads the line, so "pick up the parcel tomorrow
        at 6" arrives as a task due tomorrow with a reminder set, instead of a
        string that happens to contain the word tomorrow.
        """
        cleaned = (text or "").strip()
        if not cleaned:
            return None
        result = await self.sage.capture(cleaned)
        if result is None:
            logger.error(f"Could not add task to Sage: {cleaned}")
            return None
        await self.refresh()
        logger.info(f"Added to Sage: {cleaned}")
        return result

    async def complete_task(self, item_id: str) -> bool:
        """Tick a task off. Sage handles recurrence and the phone app's refresh."""
        updated = await self.sage.update_item(item_id, {"is_completed": True})
        if updated is None:
            return False
        await self.refresh()
        logger.info(f"Completed task {item_id}")
        return True

    async def delete_task(self, item_id: str) -> bool:
        if not await self.sage.delete_item(item_id):
            return False
        await self.refresh()
        logger.info(f"Deleted task {item_id}")
        return True

    async def push_to_esp32(self, hub):
        if not hub.connected:
            return

        formatted = []
        for item in self.items[:5]:
            title = (item.get("title") or "Untitled").strip()
            due = item.get("due_date") or item.get("start_at") or ""
            due_tag = ""
            if due:
                if "T" in due:
                    time_part = due.split("T")[1][:5]
                    due_tag = f" [{time_part}]"
                elif " " in due:
                    parts = due.split(" ")
                    if len(parts) > 1 and ":" in parts[1]:
                        due_tag = f" [{parts[1][:5]}]"

            full = f"{title}{due_tag}"
            if len(full) > 95:
                if due_tag:
                    avail = 95 - len(due_tag) - 3
                    full = f"{title[:avail]}...{due_tag}"
                else:
                    full = title[:92] + "..."
            formatted.append(full)

        await hub.send_json({
            "cmd": "SHOW_TASKS",
            "items": formatted
        })
        logger.info(f"Pushed {len(formatted)} tasks to ESP32")

    def is_alarm(self, item: dict) -> bool:
        tags = (item.get("context_tags") or "").lower()
        return SAGE_ALARM_TAG in [t.strip() for t in tags.split(",")]
