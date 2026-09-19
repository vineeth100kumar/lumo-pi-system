import asyncio
import logging
import socket
import datetime
import pytz
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import websockets
from zeroconf.asyncio import AsyncZeroconf, AsyncServiceInfo

from config import WS_PORT, HTTP_PORT, MDNS_NAME
from ws_hub import WSHub
from services.spotify import SpotifyService
from services.weather import WeatherService
from services.alarms import AlarmManager
from services.emotion import EmotionEngine
from services.tasks import TaskService
from services.system_stats import SystemStatsService

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("LumoMain")

hub = WSHub()
spotify = SpotifyService()
weather = WeatherService()
alarms = AlarmManager()
emotion = EmotionEngine()
tasks = TaskService()
system_stats = SystemStatsService()
scheduler = AsyncIOScheduler()
tz = pytz.timezone("Asia/Kolkata")

current_screen = "FACE"

def get_current_screen():
    return current_screen

# ===================== MDNS =====================
def get_local_ips():
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        primary = s.getsockname()[0]
        s.close()
        if primary and not primary.startswith("127."):
            ips.append(primary)
    except Exception:
        pass
    return ips if ips else ["127.0.0.1"]

async def start_mdns():
    zc = AsyncZeroconf()
    local_ips = get_local_ips()

    info = AsyncServiceInfo(
        "_http._tcp.local.",
        f"{MDNS_NAME}._http._tcp.local.",
        addresses=[socket.inet_aton(ip) for ip in local_ips],
        port=HTTP_PORT,
        properties={"path": "/"},
        server=f"{MDNS_NAME}.local.",
    )
    await zc.async_register_service(info)
    logger.info(f"mDNS registered: {MDNS_NAME}.local on {local_ips}")
    return zc

# ===================== CLOCK BROADCAST =====================
async def broadcast_clock():
    if not hub.connected: return
    now = datetime.datetime.now(tz)
    await hub.send_json({
        "cmd": "CLOCK",
        "h": now.hour,
        "m": now.minute,
        "weekday": now.strftime("%a"),
        "date": now.strftime("%d %b")
    })

# ===================== READY HANDSHAKE =====================
async def on_esp32_ready():
    logger.info("Sending initial synchronization to ESP32...")
    await broadcast_clock()
    await weather.poll(hub)
    await emotion.push_schedule(hub)
    await tasks.push_to_esp32(hub)
    await hub.send_json({"cmd": "SCREEN", "mode": current_screen})
    await hub.send_json({"cmd": "LIGHTS", "mode": "WARM", "brightness": 40, "hue": 0})

# ===================== BUTTON DISPATCHER =====================
async def on_button_event(btn: str):
    logger.info(f"Button pressed on ESP32: {btn}")
    if alarms.ringing_id is not None:
        alarms.dismiss()
        await hub.send_json({"cmd": "ALARM_OFF"})
        await emotion.on_alarm_dismissed(hub)
        return

    if btn == "OK":
        await spotify.toggle_play(hub)
    elif btn == "RIGHT":
        await spotify.skip_next(hub)
    elif btn == "LEFT":
        await spotify.skip_prev(hub)

# ===================== LIFESPAN =====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    hub.set_button_callback(on_button_event)
    hub.set_ready_callback(on_esp32_ready)

    ws_server = await websockets.serve(hub.handle_connection, "0.0.0.0", WS_PORT)
    logger.info(f"ESP32 WebSocket Server listening on ws://0.0.0.0:{WS_PORT}")

    zc = await start_mdns()

    scheduler.add_job(spotify.poll, "interval", seconds=2, args=[hub, emotion])
    scheduler.add_job(alarms.poll, "interval", seconds=5, args=[hub])
    scheduler.add_job(broadcast_clock, "interval", minutes=1)
    scheduler.add_job(weather.poll, "interval", minutes=30, args=[hub])
    scheduler.add_job(emotion.push_schedule, "interval", minutes=5, args=[hub])
    scheduler.add_job(system_stats.poll, "interval", seconds=2, args=[hub, get_current_screen])
    scheduler.start()

    yield

    scheduler.shutdown()
    ws_server.close()
    await ws_server.wait_closed()
    await zc.async_unregister_all_services()
    await zc.async_close()

app = FastAPI(title="LUMO Controller", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def serve_index():
    return FileResponse("static/index.html")

# ===================== REST APIS =====================

class ScreenSet(BaseModel):
    screen: str

class AlarmCreate(BaseModel):
    h: int
    m: int
    label: str = ""

class LightSet(BaseModel):
    mode: str = "WARM"
    brightness: int = 50
    hue: int = 0

class TaskCreate(BaseModel):
    text: str

class EmotionSet(BaseModel):
    mood: str = "NORMAL"

@app.get("/api/status")
async def get_status():
    now = datetime.datetime.now(tz)
    return {
        "esp32_connected": hub.connected,
        "screen": current_screen,
        "time": now.strftime("%H:%M"),
        "date": now.strftime("%a %d %b"),
        "temp_c": weather.last_temp,
        "weather_icon": weather.last_icon,
        "mood": emotion.current_mood,
        "schedule": emotion.current_schedule,
        "alarm_ringing": alarms.ringing_id is not None,
        "system": system_stats.get_all(),
        "spotify": {
            "playing": spotify.is_playing,
            "title": getattr(spotify, "last_track_id", "")
        }
    }

# Screen Mode Control
@app.post("/api/screen")
async def set_screen(item: ScreenSet):
    global current_screen
    current_screen = item.screen.upper()
    await hub.send_json({"cmd": "SCREEN", "mode": current_screen})
    if current_screen == "SYSTEM":
        await system_stats.poll(hub, get_current_screen)
    logger.info(f"Screen switched via Web UI -> {current_screen}")
    return {"ok": True, "screen": current_screen}

# Alarms
@app.get("/api/alarms")
async def get_alarms():
    return alarms.list_alarms()

@app.post("/api/alarms")
async def create_alarm(item: AlarmCreate):
    a = alarms.add_alarm(item.h, item.m, item.label)
    return a.to_dict()

@app.delete("/api/alarms/{alarm_id}")
async def remove_alarm(alarm_id: int):
    alarms.delete_alarm(alarm_id)
    return {"ok": True}

@app.post("/api/alarms/{alarm_id}/toggle")
async def toggle_alarm(alarm_id: int):
    alarms.toggle_alarm(alarm_id)
    return {"ok": True}

@app.post("/api/alarms/snooze")
async def snooze_alarm():
    alarms.snooze()
    await hub.send_json({"cmd": "ALARM_OFF"})
    return {"ok": True}

@app.post("/api/alarms/dismiss")
async def dismiss_alarm():
    alarms.dismiss()
    await hub.send_json({"cmd": "ALARM_OFF"})
    await emotion.on_alarm_dismissed(hub)
    return {"ok": True}

# Tasks
@app.get("/api/tasks")
async def get_tasks():
    return tasks.get_tasks()

@app.post("/api/tasks")
async def add_task(item: TaskCreate):
    tasks.add_task(item.text)
    await tasks.push_to_esp32(hub)
    return {"ok": True}

@app.delete("/api/tasks/{index}")
async def remove_task(index: int):
    tasks.delete_task(index)
    await tasks.push_to_esp32(hub)
    return {"ok": True}

# Lights
@app.post("/api/lights")
async def set_lights(item: LightSet):
    await hub.send_json({
        "cmd": "LIGHTS",
        "mode": item.mode.upper(),
        "brightness": item.brightness,
        "hue": item.hue
    })
    return {"ok": True}

# Haptics
@app.post("/api/haptic")
async def trigger_haptic(ms: int = 50):
    await hub.send_json({"cmd": "HAPTIC", "ms": ms})
    return {"ok": True}

# Emotion
@app.post("/api/emotion")
async def set_emotion(item: EmotionSet):
    await emotion.push_schedule(hub, item.mood.upper())
    return {"ok": True}

# Spotify Remote
@app.post("/api/spotify/next")
async def spotify_next():
    await spotify.skip_next(hub)
    return {"ok": True}

@app.post("/api/spotify/prev")
async def spotify_prev():
    await spotify.skip_prev(hub)
    return {"ok": True}

@app.post("/api/spotify/toggle")
async def spotify_toggle():
    await spotify.toggle_play(hub)
    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=HTTP_PORT, reload=False)
