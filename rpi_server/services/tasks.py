import os
import json
import logging
from config import TASK_FILE

logger = logging.getLogger("TaskService")

class TaskService:
    def __init__(self):
        self.tasks: list[str] = []
        self._load()

    def _load(self):
        if os.path.exists(TASK_FILE):
            try:
                with open(TASK_FILE, "r") as f:
                    data = json.load(f)
                self.tasks = data.get("tasks", [])
            except Exception as e:
                logger.error(f"Error loading tasks.json: {e}")
                self.tasks = []
        else:
            self.tasks = ["Review LUMO Code", "Enjoy Music", "Plan Next Project"]
            self._save()

    def _save(self):
        try:
            with open(TASK_FILE, "w") as f:
                json.dump({"tasks": self.tasks}, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving tasks.json: {e}")

    def get_tasks(self) -> list[str]:
        return self.tasks

    def add_task(self, text: str):
        cleaned = text.strip()
        if cleaned:
            self.tasks.append(cleaned)
            self._save()
            logger.info(f"Added task: {cleaned}")

    def delete_task(self, index: int):
        if 0 <= index < len(self.tasks):
            removed = self.tasks.pop(index)
            self._save()
            logger.info(f"Removed task: {removed}")

    async def push_to_esp32(self, hub):
        if not hub.connected: return
        await hub.send_json({
            "cmd": "SHOW_TASKS",
            "items": self.tasks[:5]
        })
        logger.info("Pushed top 5 tasks to ESP32")
