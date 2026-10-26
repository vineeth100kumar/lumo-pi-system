# Code map

**This repo is frozen.** LUMO moved into
[vineeth100kumar/TASK_MANAGER](https://github.com/vineeth100kumar/TASK_MANAGER)
under `lumo/` (history kept). Live work happens there:

| Now lives in TASK_MANAGER | What |
| --- | --- |
| `lumo/esp32_client/` | Clock firmware (much newer than here) |
| `raspberry_pi/desk/` | What drives the clock now, inside Sage's server |
| `lumo/rpi_server/` | A copy of this repo's `rpi_server/`, retired |
| `CODEMAP.md` | The full map |

Checked on 2026-10-26. The rest describes this repo as it was left.

## Layout

| Path | What it does |
| --- | --- |
| `esp32_client/esp32_client.ino` | Firmware setup and loop (ESP32-C3) |
| `esp32_client/ws_client.cpp` | Websocket link to the Pi |
| `esp32_client/display.cpp`, `animator.cpp` | ILI9341 screens, animations |
| `esp32_client/peripherals.cpp` | Buttons, NeoPixels, buzzer |
| `esp32_client/config.h` | Pins and constants |
| `rpi_server/main.py` | FastAPI app (HTTPS :8080, http :8081) + websocket hub (:8765) |
| `rpi_server/ws_hub.py` | Clock websocket connections |
| `rpi_server/config.py`, `.env.example` | Settings |
| `rpi_server/services/sage_client.py`, `tasks.py` | Tasks from Sage |
| `rpi_server/services/alarms.py` | Alarms |
| `rpi_server/services/spotify.py`, `weather.py`, `system_stats.py` | Now playing, weather, Pi vitals |
| `rpi_server/services/emotion.py`, `animation_engine.py` | Mood and expressions |
| `rpi_server/services/bluetooth_manager.py`, `ios_companion.py` | Bluetooth audio, iPhone link |
| `rpi_server/services/memories.py`, `vision_curator.py`, `cascades/` | Photo memories, face-safe crop |
| `rpi_server/services/voice/` | Voice assistant: capture, Groq STT, Edge TTS, brain |
| `rpi_server/static/index.html` | Web dashboard |
| `rpi_server/lumo.service`, `lumo-obex.service` | systemd units |
| `rpi_server/test_mic.py`, `test_sage.py`, `scratch/` | Manual test scripts |

## HTTP API (`rpi_server/main.py`)

| Area | Routes |
| --- | --- |
| Status | `GET /`, `GET /api/status` |
| Bluetooth | `GET /api/bluetooth/status`, `POST .../pair-mode`, `.../pair-mode/stop`, `.../wearable-mode`, `.../connect`, `.../disconnect`, `.../ping`, `DELETE .../device/{mac}` |
| Music | `GET /api/music/art`, `POST .../resend-art`, `.../toggle-swap`, `.../toggle-bgr`, `POST /api/spotify/next`, `/prev`, `/toggle` |
| Screen | `POST /api/animation/play`, `/api/animation/color`, `/api/notification`, `/api/screen`, `/api/lights`, `/api/haptic`, `/api/emotion` |
| Alarms | `GET/POST /api/alarms`, `DELETE /api/alarms/{id}`, `POST .../{id}/toggle`, `.../snooze`, `.../dismiss` |
| Tasks | `GET/POST /api/tasks`, `POST /api/tasks/{id}/complete`, `DELETE /api/tasks/{id}` |
| Voice | `GET /api/voice/status`, `POST .../push-to-talk`, `.../text-command`, `GET .../last-audio.mp3`, `GET .../devices`, `POST .../device` |
| Memories | `GET /api/memories`, `POST .../upload`, `.../shortcut`, `.../next`, `.../prev`, `.../push`, `.../curate/scan`, `.../curate/override`, `.../config`, `DELETE .../{id}` |
