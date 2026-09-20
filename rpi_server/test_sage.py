#!/usr/bin/env python3
"""
Check Lumo's connection to Sage, the shared task manager.

Run this on the Pi after wiring the two together:

    cd /home/pi/lumo_pi_system/rpi_server
    sudo systemctl show sage-backend -p Environment   # where the key comes from
    venv/bin/python test_sage.py

It reads the real lists, creates a throwaway alarm and removes it again, and
waits a moment on the event stream. Nothing else is written.
"""

import asyncio
import sys

from services.sage_client import SageClient, key_search_report
from services.tasks import TaskService
from services.alarms import AlarmManager


async def main() -> int:
    sage = SageClient()
    print(f"Sage at {sage.base_url}")

    if not sage.is_configured:
        print("\nNo API key found. Looked in:")
        for place in key_search_report().split("; "):
            print(f"    {place}")
        print("\n  Running main.py by hand? Put the key in rpi_server/.env:")
        print("    SAGE_API_KEY=<the same key the Sage app asks for>")
        print("  Under systemd, lumo.service reads it from /etc/sage/sage.env.")
        return 1
    print(f"Key found, ending in ...{sage.api_key[-4:]}")

    tasks = TaskService(sage)
    alarms = AlarmManager(sage)

    await tasks.refresh()
    if not sage.online:
        print(f"\nCould not reach Sage: {sage.last_error}")
        print("  Is it running?  sudo systemctl status sage-backend")
        return 1
    if sage.last_error:
        print(f"\n{sage.last_error}")
        return 1

    open_tasks = tasks.get_tasks()
    print(f"\n{len(open_tasks)} open task(s):")
    for title in open_tasks[:5]:
        print(f"  - {title}")

    await alarms.refresh()
    print(f"\n{len(alarms.list_alarms())} alarm(s):")
    for a in alarms.list_alarms():
        print(f"  - {a['h']:02d}:{a['m']:02d}  {a['label']}  {'on' if a['enabled'] else 'off'}")

    print("\nWriting a throwaway alarm...")
    probe = await alarms.add_alarm(4, 44, "Lumo connection test")
    if probe is None:
        print(f"  Could not write to Sage: {sage.last_error}")
        return 1
    print(f"  Created {probe.id}, set for {probe.h:02d}:{probe.m:02d}")
    await alarms.delete_alarm(probe.id)
    print("  Removed it again")

    print("\nListening for live events for 5 seconds...")
    seen = []
    listener = asyncio.create_task(sage.listen(lambda e: _note(seen, e)))
    await asyncio.sleep(5)
    listener.cancel()
    if any(e.get("type") == "AUTH_OK" for e in seen):
        print("  Event stream connected and authenticated")
    else:
        print("  No handshake seen. Reminders will not reach the display.")
        await sage.close()
        return 1

    await sage.close()
    print("\nAll good. Lumo and Sage are sharing one list.")
    return 0


async def _note(seen: list, event: dict) -> None:
    seen.append(event)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
