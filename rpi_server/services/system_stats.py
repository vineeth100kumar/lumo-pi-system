import os
import shutil
import logging

logger = logging.getLogger("SystemStats")

class SystemStatsService:
    def __init__(self):
        self.last_cpu_temp = 0.0
        self.last_cpu_pct = 0
        self.last_ram_pct = 0
        self.last_disk_pct = 0
        self._prev_idle = 0
        self._prev_total = 0

    def get_cpu_temp(self) -> float:
        try:
            with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                return round(int(f.read().strip()) / 1000.0, 1)
        except Exception:
            return 0.0

    def get_cpu_pct(self) -> int:
        try:
            with open("/proc/stat", "r") as f:
                line = f.readline()
            parts = [float(x) for x in line.split()[1:8]]
            idle = parts[3] + parts[4]
            total = sum(parts)
            diff_idle = idle - self._prev_idle
            diff_total = total - self._prev_total
            self._prev_idle = idle
            self._prev_total = total
            if diff_total > 0:
                pct = int((1.0 - diff_idle / diff_total) * 100)
                return max(0, min(100, pct))
        except Exception:
            pass
        return 0

    def get_ram_pct(self) -> int:
        try:
            with open("/proc/meminfo", "r") as f:
                lines = f.readlines()
            mem = {}
            for l in lines:
                parts = l.split(":")
                if len(parts) == 2:
                    mem[parts[0].strip()] = int(parts[1].split()[0])
            total = mem.get("MemTotal", 1)
            avail = mem.get("MemAvailable", mem.get("MemFree", 0))
            return int((1.0 - avail / total) * 100)
        except Exception:
            return 0

    def get_disk_pct(self) -> int:
        try:
            usage = shutil.disk_usage("/")
            return int((usage.used / usage.total) * 100)
        except Exception:
            return 0

    def get_all(self) -> dict:
        return {
            "cpu_temp": self.get_cpu_temp(),
            "cpu_pct": self.get_cpu_pct(),
            "ram_pct": self.get_ram_pct(),
            "disk_pct": self.get_disk_pct()
        }

    async def poll(self, hub, get_screen_fn):
        stats = self.get_all()
        self.last_cpu_temp = stats["cpu_temp"]
        self.last_cpu_pct  = stats["cpu_pct"]
        self.last_ram_pct  = stats["ram_pct"]
        self.last_disk_pct = stats["disk_pct"]

        current_screen = get_screen_fn()
        if hub.connected and current_screen == "SYSTEM":
            await hub.send_json({
                "cmd": "SYSTEM_STATS",
                "cpu_temp": stats["cpu_temp"],
                "cpu_pct": stats["cpu_pct"],
                "ram_pct": stats["ram_pct"],
                "disk_pct": stats["disk_pct"]
            })
