import asyncio
import logging
import socket
import datetime
import pytz
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from io import BytesIO
from typing import Optional
from pydantic import BaseModel
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import websockets
from zeroconf.asyncio import AsyncZeroconf, AsyncServiceInfo

from config import WS_PORT, HTTP_PORT, HTTP_PLAIN_PORT, MDNS_NAME, SAGE_REFRESH_SECONDS
from ws_hub import WSHub
from services.sage_client import SageClient, key_search_report
from services.spotify import SpotifyService
from services.weather import WeatherService
from services.alarms import AlarmManager
from services.emotion import EmotionEngine
from services.tasks import TaskService
from services.system_stats import SystemStatsService
from services.animation_engine import AnimationEngine
from services.ios_companion import IOSCompanionService
from services.bluetooth_manager import BluetoothManager
from services.voice import VoiceService, VoiceState
from services.memories import MemoriesService

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler

    class InboxHandler(FileSystemEventHandler):
        def __init__(self, loop, memories, hub):
            self.loop = loop
            self.memories = memories
            self.hub = hub

        def on_created(self, event):
            if event.is_directory:
                return
            asyncio.run_coroutine_threadsafe(
                self.memories.ingest_from_path(event.src_path, self.hub),
                self.loop
            )
except ImportError:
    Observer = None
    InboxHandler = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("LumoMain")
logging.getLogger("apscheduler").setLevel(logging.WARNING)

hub = WSHub()
sage = SageClient()
spotify = SpotifyService()
weather = WeatherService()
alarms = AlarmManager(sage)
emotion = EmotionEngine()
tasks = TaskService(sage)
system_stats = SystemStatsService()
anim_engine = AnimationEngine()
ios_companion = IOSCompanionService()
bt_manager = BluetoothManager()
memories = MemoriesService()
voice_service = VoiceService(hub=hub, anim_engine=anim_engine)
scheduler = AsyncIOScheduler()
tz = pytz.timezone("Asia/Kolkata")

last_interaction = time.time()

def touch_interaction():
    global last_interaction
    last_interaction = time.time()

current_screen = "FACE"

def get_current_screen():
    return current_screen

memory_timer_task: Optional[asyncio.Task] = None

def _cancel_memory_timer():
    global memory_timer_task
    if memory_timer_task and not memory_timer_task.done():
        memory_timer_task.cancel()
    memory_timer_task = None

def _start_memory_static_timer():
    global memory_timer_task
    _cancel_memory_timer()
    async def _timer():
        try:
            await asyncio.sleep(memories.interval_sec)
            if current_screen == "MEMORY" and memories.auto_rotate:
                await memories_auto_advance()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f"Memory static timer error: {e}")
    memory_timer_task = asyncio.create_task(_timer())

async def memories_auto_advance():
    if current_screen == "MEMORY" and memories.auto_rotate and memories.photos:
        _cancel_memory_timer()
        await memories.next_photo(hub, on_advance=memories_auto_advance)
        if not memories.is_gif_streaming():
            _start_memory_static_timer()

async def show_memory_current():
    _cancel_memory_timer()
    ok = await memories.push_current(hub, on_advance=memories_auto_advance)
    if ok and current_screen == "MEMORY" and memories.auto_rotate and not memories.is_gif_streaming():
        _start_memory_static_timer()

async def set_screen_mode(screen: str):
    global current_screen
    touch_interaction()
    old_screen = current_screen
    current_screen = screen.upper()
    if old_screen == "MEMORY" and current_screen != "MEMORY":
        _cancel_memory_timer()
        memories.stop_gif_playback()
    await hub.send_json({"cmd": "SCREEN", "mode": current_screen})
    if current_screen == "SYSTEM":
        await system_stats.poll(hub, get_current_screen)
    elif current_screen == "MEMORY":
        await show_memory_current()
    logger.info(f"Screen switched -> {current_screen}")

# Wire all live services into JARVIS Voice Brain
voice_service.update_services({
    "spotify": spotify,
    "weather": weather,
    "alarms": alarms,
    "emotion": emotion,
    "tasks": tasks,
    "system_stats": system_stats,
    "anim_engine": anim_engine,
    "ios_companion": ios_companion,
    "bt_manager": bt_manager,
    "memories": memories,
    "set_screen": set_screen_mode,
    "get_screen": get_current_screen,
}, hub=hub)

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
    await hub.send_json({"cmd": "SCREEN", "mode": current_screen})
    await hub.send_json({"cmd": "LIGHTS", "mode": "WARM", "brightness": 40, "hue": 0})
    if current_screen == "MEMORY":
        await show_memory_current()
    # Background sync for external data
    await emotion.push_schedule(hub)
    await tasks.push_to_esp32(hub)
    await weather.poll(hub)

# ===================== SAGE EVENT BRIDGE =====================
async def refresh_from_sage():
    """Re-read both lists and show the current tasks on the display."""
    await tasks.refresh()
    await alarms.refresh()
    await tasks.push_to_esp32(hub)

async def on_sage_event(event: dict):
    """
    Anything that happens in the task manager, felt at the desk.

    A reminder falling due is either one of Lumo's alarms, in which case the
    clock has already sounded it and this is the same event arriving a moment
    later, or it is an ordinary Sage reminder, which becomes a buzz and a card
    on the face.
    """
    kind = event.get("type")
    data = event.get("data") or {}

    if kind == "REMINDER_TRIGGERED":
        item_id = data.get("id", "")
        if any(a.id == item_id for a in alarms.alarms):
            if alarms.mark_fired(item_id) and alarms.ringing_id is None:
                alarms.ringing_id = item_id
                await hub.send_json({"cmd": "ALARM_RING"})
            return
        title = data.get("title") or "Reminder"
        logger.info(f"Sage reminder due: {title}")
        await ios_companion.push_notification("Sage", title, "Due now", hub)
        return

    if kind in ("ITEM_CREATED", "ITEM_UPDATED", "ITEM_DELETED", "TASKS_MIGRATED"):
        await refresh_from_sage()

# ===================== BUTTON DISPATCHER =====================
async def on_button_event(btn: str):
    logger.info(f"Button pressed on ESP32: {btn}")
    touch_interaction()
    if alarms.ringing_id is not None:
        await alarms.dismiss()
        await hub.send_json({"cmd": "ALARM_OFF"})
        await emotion.on_alarm_dismissed(hub)
        return

    if current_screen == "MEMORY":
        if btn == "LEFT":
            _cancel_memory_timer()
            await memories.prev_photo(hub, on_advance=memories_auto_advance)
            if not memories.is_gif_streaming() and memories.auto_rotate:
                _start_memory_static_timer()
            return
        elif btn == "RIGHT":
            _cancel_memory_timer()
            await memories.next_photo(hub, on_advance=memories_auto_advance)
            if not memories.is_gif_streaming() and memories.auto_rotate:
                _start_memory_static_timer()
            return
        elif btn == "OK":
            _cancel_memory_timer()
            memories.stop_gif_playback()
            await set_screen_mode("FACE")
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

    # Tasks and alarms live in Sage. Load them once at boot, then follow its
    # event stream; the scheduled refresh below is only a safety net for an
    # event missed while the connection was down.
    if not sage.is_configured:
        logger.warning(
            "No Sage API key found, so tasks and alarms will be empty. "
            "Put SAGE_API_KEY in rpi_server/.env (the same key the Sage app "
            "asks for), or run Lumo under systemd, where lumo.service reads "
            "it from /etc/sage/sage.env."
        )
        logger.warning(f"Looked in: {key_search_report()}")
    await refresh_from_sage()
    sage_listener = asyncio.create_task(sage.listen(on_sage_event))

    zc = await start_mdns()

    scheduler.add_job(spotify.poll, "interval", seconds=2, args=[hub, emotion])
    scheduler.add_job(alarms.poll, "interval", seconds=5, args=[hub])
    scheduler.add_job(broadcast_clock, "interval", minutes=1)
    scheduler.add_job(weather.poll, "interval", minutes=30, args=[hub])
    scheduler.add_job(emotion.push_schedule, "interval", minutes=5, args=[hub])
    scheduler.add_job(system_stats.poll, "interval", seconds=2, args=[hub, get_current_screen])
    scheduler.add_job(refresh_from_sage, "interval", seconds=SAGE_REFRESH_SECONDS)

    async def anim_poll_wrapper():
        is_music = spotify.is_playing or ios_companion.is_playing
        await anim_engine.poll_idle(hub, get_current_screen(), is_music)

    async def bt_poll_wrapper():
        await ios_companion.poll_bluetooth_media(hub, anim_engine)

    async def bt_events_wrapper():
        await bt_manager.poll_connection_events(hub, anim_engine)

    async def memories_ambient_check():
        if not memories.auto_rotate or not memories.photos:
            return
        idle_time = time.time() - last_interaction
        if idle_time > 120 and current_screen in ("FACE", "CLOCK"):
            await set_screen_mode("MEMORY")

    scheduler.add_job(anim_poll_wrapper, "interval", seconds=2)
    scheduler.add_job(bt_poll_wrapper, "interval", seconds=2)
    scheduler.add_job(bt_events_wrapper, "interval", seconds=2)
    scheduler.add_job(memories_ambient_check, "interval", seconds=10)
    scheduler.start()

    # Watchdog file watcher for OBEX inbox
    observer = None
    if Observer and InboxHandler:
        loop = asyncio.get_running_loop()
        event_handler = InboxHandler(loop, memories, hub)
        observer = Observer()
        observer.schedule(event_handler, path=memories.inbox_dir, recursive=False)
        try:
            observer.start()
            logger.info(f"Memories watchdog observer started on {memories.inbox_dir}")
        except Exception as e:
            logger.warning(f"Could not start watchdog observer: {e}")
            observer = None

    # Background verification: ensure library photos are curated
    if memories.photos:
        asyncio.create_task(asyncio.to_thread(memories.scan_and_curate_all))

    voice_service.update_services({
        "hub": hub,
        "anim_engine": anim_engine,
        "ios_companion": ios_companion,
        "spotify": spotify,
        "system_stats": system_stats,
        "alarms": alarms,
        "tasks": tasks,
        "weather": weather,
        "memories": memories,
        "set_screen": set_screen_mode,
    }, hub=hub)
    loop = asyncio.get_running_loop()
    voice_service.start(loop=loop)

    yield

    if observer:
        observer.stop()
        observer.join()

    voice_service.stop()
    sage_listener.cancel()
    await sage.close()
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

class AnimPlay(BaseModel):
    anim: str
    duration: float = 2.5

class AnimColor(BaseModel):
    color: str

class NotifPush(BaseModel):
    app: str = "iPhone"
    title: str
    body: str

class BtMac(BaseModel):
    mac: str

@app.get("/api/status")
async def get_status():
    now = datetime.datetime.now(tz)
    bt_status = await bt_manager.get_status()
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
        "eye_color": anim_engine.current_color,
        "animation": anim_engine.current_anim,
        "spotify": {
            "playing": spotify.is_playing,
            "title": getattr(spotify, "last_track_id", "")
        },
        "ios_music": {
            "connected": ios_companion.is_connected or bt_status.get("connected", False),
            "playing": ios_companion.is_playing,
            "title": ios_companion.current_title,
            "artist": ios_companion.current_artist,
            "album": ios_companion.current_album,
            "progress_ms": ios_companion.progress_ms,
            "duration_ms": ios_companion.duration_ms,
            "has_art": ios_companion.last_img is not None
        },
        "bluetooth": bt_status,
        "memories": {
            "count": len(memories.photos),
            "max_photos": memories.max_photos,
            "nightly_quota": memories.nightly_quota,
            "nightly_used": memories.get_nightly_upload_count(),
            "nightly_remaining": memories.get_nightly_remaining(),
            "replace_duplicates": memories.replace_duplicates,
            "gif_loops": memories.gif_loops,
            "curate_display": memories.curate_display,
            "curation_stats": memories.get_curation_stats(),
            "current_index": memories.current_index,
            "auto_rotate": memories.auto_rotate,
            "interval_sec": memories.interval_sec,
            "current": memories.get_current()
        },
        "voice": voice_service.get_status(),
        "sage": sage.status()
    }

@app.get("/api/music/art")
async def get_current_art():
    if ios_companion.last_img:
        img_io = BytesIO()
        ios_companion.last_img.save(img_io, format="JPEG", quality=92)
        img_io.seek(0)
        return Response(content=img_io.getvalue(), media_type="image/jpeg")
    raise HTTPException(status_code=404, detail="No artwork available")

# Bluetooth Pairing & Device APIs
@app.get("/api/bluetooth/status")
async def get_bluetooth_status():
    return await bt_manager.get_status()

@app.post("/api/bluetooth/pair-mode")
async def start_bt_pairing():
    res = await bt_manager.start_pairing_mode(timeout_sec=180, hub=hub)
    return res

@app.post("/api/bluetooth/pair-mode/stop")
async def stop_bt_pairing():
    return await bt_manager.stop_pairing_mode()

@app.post("/api/bluetooth/wearable-mode")
async def apply_wearable_mode():
    res = await bt_manager.apply_wearable_config()
    return res

@app.post("/api/bluetooth/connect")
async def connect_bt(item: BtMac):
    return await bt_manager.connect_device(item.mac)

@app.post("/api/bluetooth/disconnect")
async def disconnect_bt(item: BtMac):
    return await bt_manager.disconnect_device(item.mac)

@app.delete("/api/bluetooth/device/{mac}")
async def remove_bt_device(mac: str):
    return await bt_manager.remove_device(mac)

@app.post("/api/bluetooth/ping")
async def ping_bt():
    await hub.send_json({"cmd": "HAPTIC", "ms": 70})
    await hub.send_json({
        "cmd": "NOTIF",
        "app": "Bluetooth",
        "title": "Ping OK",
        "body": "Signal verified!"
    })
    return {"ok": True}

# Album Art Calibration & Live Correction APIs
@app.post("/api/music/resend-art")
async def resend_album_art():
    if ios_companion.last_img:
        art_bytes = ios_companion.encode_image_to_buffer(ios_companion.last_img)
        await hub.send_binary(art_bytes)
        return {"ok": True, "cached": True}
    elif ios_companion.current_title:
        art_bytes = await ios_companion.fetch_itunes_album_art(ios_companion.current_title, ios_companion.current_artist)
        if art_bytes:
            await hub.send_binary(art_bytes)
        return {"ok": True, "fetched": True}
    return {"ok": False, "error": "No track active"}

@app.post("/api/music/toggle-swap")
async def toggle_art_swap():
    ios_companion.swap_bytes = not ios_companion.swap_bytes
    if ios_companion.last_img:
        art_bytes = ios_companion.encode_image_to_buffer(ios_companion.last_img)
        await hub.send_binary(art_bytes)
    logger.info(f"Toggled album art swap_bytes -> {ios_companion.swap_bytes}")
    return {"ok": True, "swap_bytes": ios_companion.swap_bytes}

@app.post("/api/music/toggle-bgr")
async def toggle_art_bgr():
    ios_companion.bgr_mode = not ios_companion.bgr_mode
    if ios_companion.last_img:
        art_bytes = ios_companion.encode_image_to_buffer(ios_companion.last_img)
        await hub.send_binary(art_bytes)
    logger.info(f"Toggled album art bgr_mode -> {ios_companion.bgr_mode}")
    return {"ok": True, "bgr_mode": ios_companion.bgr_mode}

# Animation & Expression Studio APIs
@app.post("/api/animation/play")
async def play_animation(item: AnimPlay):
    await anim_engine.play_animation(item.anim, hub, item.duration)
    return {"ok": True, "anim": item.anim}

@app.post("/api/animation/color")
async def set_eye_color(item: AnimColor):
    ok = await anim_engine.set_eye_color(item.color, hub)
    return {"ok": ok, "color": item.color}

@app.post("/api/notification")
async def push_notification_alert(item: NotifPush):
    await ios_companion.push_notification(item.app, item.title, item.body, hub)
    return {"ok": True}

# Screen Mode Control
@app.post("/api/screen")
async def set_screen(item: ScreenSet):
    await set_screen_mode(item.screen)
    return {"ok": True, "screen": current_screen}

# Alarms
@app.get("/api/alarms")
async def get_alarms():
    return alarms.list_alarms()

@app.post("/api/alarms")
async def create_alarm(item: AlarmCreate):
    a = await alarms.add_alarm(item.h, item.m, item.label)
    if a is None:
        raise HTTPException(status_code=503, detail=sage.last_error or "Sage unavailable")
    return a.to_dict()

@app.delete("/api/alarms/{alarm_id}")
async def remove_alarm(alarm_id: str):
    if not await alarms.delete_alarm(alarm_id):
        raise HTTPException(status_code=503, detail=sage.last_error or "Sage unavailable")
    return {"ok": True}

@app.post("/api/alarms/{alarm_id}/toggle")
async def toggle_alarm(alarm_id: str):
    if not await alarms.toggle_alarm(alarm_id):
        raise HTTPException(status_code=503, detail=sage.last_error or "Sage unavailable")
    return {"ok": True}

@app.post("/api/alarms/snooze")
async def snooze_alarm():
    await alarms.snooze()
    await hub.send_json({"cmd": "ALARM_OFF"})
    return {"ok": True}

@app.post("/api/alarms/dismiss")
async def dismiss_alarm():
    await alarms.dismiss()
    await hub.send_json({"cmd": "ALARM_OFF"})
    await emotion.on_alarm_dismissed(hub)
    return {"ok": True}

# Tasks (stored in Sage)
@app.get("/api/tasks")
async def get_tasks():
    return {"tasks": tasks.get_tasks(), "items": tasks.get_items()}

@app.post("/api/tasks")
async def add_task(item: TaskCreate):
    created = await tasks.add_task(item.text)
    if created is None:
        raise HTTPException(status_code=503, detail=sage.last_error or "Sage unavailable")
    await tasks.push_to_esp32(hub)
    return {"ok": True, "result": created}

@app.post("/api/tasks/{item_id}/complete")
async def complete_task(item_id: str):
    if not await tasks.complete_task(item_id):
        raise HTTPException(status_code=503, detail=sage.last_error or "Sage unavailable")
    await tasks.push_to_esp32(hub)
    return {"ok": True}

@app.delete("/api/tasks/{item_id}")
async def remove_task(item_id: str):
    if not await tasks.delete_task(item_id):
        raise HTTPException(status_code=503, detail=sage.last_error or "Sage unavailable")
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

# Media Controls (iOS Bluetooth / Spotify)
@app.post("/api/spotify/next")
async def spotify_next():
    if ios_companion.is_connected or getattr(bt_manager, "is_connected", False):
        await ios_companion.next_track()
        return {"ok": True, "source": "ios"}
    await spotify.skip_next(hub)
    return {"ok": True, "source": "spotify"}

@app.post("/api/spotify/prev")
async def spotify_prev():
    if ios_companion.is_connected or getattr(bt_manager, "is_connected", False):
        await ios_companion.prev_track()
        return {"ok": True, "source": "ios"}
    await spotify.skip_prev(hub)
    return {"ok": True, "source": "spotify"}

@app.post("/api/spotify/toggle")
async def spotify_toggle():
    if ios_companion.is_connected or getattr(bt_manager, "is_connected", False):
        await ios_companion.toggle_play()
        return {"ok": True, "source": "ios"}
    await spotify.toggle_play(hub)
    return {"ok": True, "source": "spotify"}

# ===================== JARVIS VOICE ASSISTANT =====================

class VoicePrompt(BaseModel):
    prompt: str

@app.get("/api/voice/status")
async def get_voice_status():
    return voice_service.get_status()

@app.post("/api/voice/push-to-talk")
async def voice_push_to_talk(request: Request):
    audio_bytes = await request.body()
    if not audio_bytes or len(audio_bytes) < 100:
        raise HTTPException(status_code=400, detail="Empty or invalid audio data")
    mime_type = request.headers.get("content-type")
    res = await voice_service.process_voice_turn(audio_bytes, mime_type=mime_type)
    return res

@app.post("/api/voice/text-command")
async def voice_text_command(item: VoicePrompt):
    if not item.prompt or not item.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")
    res = await voice_service.process_text_turn(item.prompt.strip())
    return res

@app.get("/api/voice/last-audio.mp3")
async def get_last_voice_audio():
    if voice_service.tts.last_audio_bytes:
        return Response(content=voice_service.tts.last_audio_bytes, media_type="audio/mpeg")
    raise HTTPException(status_code=404, detail="No voice audio available")

class VoiceDeviceSelect(BaseModel):
    device: str

@app.get("/api/voice/devices")
async def get_voice_devices():
    return {
        "current_device": voice_service.audio_capture.device,
        "is_capturing": voice_service.audio_capture.is_capturing,
        "devices": voice_service.audio_capture.list_devices()
    }

@app.post("/api/voice/device")
async def set_voice_device(item: VoiceDeviceSelect):
    loop = asyncio.get_running_loop()
    ok = voice_service.audio_capture.set_device(item.device, loop=loop)
    return {"ok": ok, "device": voice_service.audio_capture.device}

# ===================== MEMORIES PHOTO FRAME =====================

class MemoryConfig(BaseModel):
    auto_rotate: Optional[bool] = None
    interval_sec: Optional[int] = None
    swap_bytes: Optional[bool] = None
    bgr_mode: Optional[bool] = None
    max_photos: Optional[int] = None
    nightly_quota: Optional[int] = None
    reset_nightly: Optional[bool] = None
    replace_duplicates: Optional[bool] = None
    gif_loops: Optional[int] = None
    curate_display: Optional[bool] = None

class CurationOverride(BaseModel):
    id: str
    category: str

@app.get("/api/memories")
async def get_memories():
    return {
        "photos": memories.list_photos(),
        "current_index": memories.current_index,
        "auto_rotate": memories.auto_rotate,
        "interval_sec": memories.interval_sec,
        "swap_bytes": memories.swap_bytes,
        "bgr_mode": memories.bgr_mode,
        "max_photos": memories.max_photos,
        "nightly_quota": memories.nightly_quota,
        "nightly_used": memories.get_nightly_upload_count(),
        "nightly_remaining": memories.get_nightly_remaining(),
        "replace_duplicates": memories.replace_duplicates,
        "gif_loops": memories.gif_loops,
        "curate_display": memories.curate_display,
        "curation_stats": memories.get_curation_stats(),
    }

async def _process_memory_upload(request: Request, default_source: str = "upload", default_display: bool = False):
    caption = request.query_params.get("caption") or request.headers.get("x-caption")
    display_param = request.query_params.get("display")
    should_display = default_display
    if display_param is not None:
        should_display = display_param.lower() in ("true", "1", "yes")

    source = request.query_params.get("source") or default_source
    saved_items = []

    force = request.query_params.get("force", "").lower() in ("true", "1", "yes")

    # Check nightly quota for automated Apple Shortcuts sync if configured (> 0)
    is_automated_sync = (source == "apple_shortcut" or default_source == "apple_shortcut") and not force
    if is_automated_sync and memories.nightly_quota > 0:
        remaining_nightly = memories.get_nightly_remaining()
        if remaining_nightly <= 0:
            return {
                "ok": False,
                "quota_reached": True,
                "count": 0,
                "message": f"Nightly quota reached: {memories.nightly_quota}/{memories.nightly_quota} photos already synced tonight. Next sync tomorrow night!",
                "nightly_used": memories.get_nightly_upload_count(),
                "nightly_quota": memories.nightly_quota,
                "total_count": len(memories.photos),
                "total_quota": memories.max_photos,
                "photos": []
            }

    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" in content_type:
        form = await request.form()
        if "caption" in form and form["caption"]:
            caption = str(form["caption"])
        if "display" in form and form["display"]:
            should_display = str(form["display"]).lower() in ("true", "1", "yes")

        # Collect all UploadFile objects from any field names (file, files, photo, image, etc.)
        files_to_process = []
        for key, val in form.multi_items():
            if isinstance(val, UploadFile):
                files_to_process.append(val)

        # If automated sync and nightly limit configured, cap batch to remaining slots
        if is_automated_sync and memories.nightly_quota > 0:
            remaining_nightly = memories.get_nightly_remaining()
            if remaining_nightly < len(files_to_process):
                files_to_process = files_to_process[:remaining_nightly]

        is_batch = len(files_to_process) > 1

        for file_obj in files_to_process:
            raw_bytes = await file_obj.read()
            if not raw_bytes or len(raw_bytes) < 50:
                continue
            fname = file_obj.filename or "upload.jpg"
            # For batch uploads, suppress individual per-image haptic/notif to avoid buzzing 10 times
            item = await memories.ingest_bytes(
                raw_bytes,
                hub=hub,
                source=source,
                filename=fname,
                caption=caption,
                notify=not is_batch
            )
            if item:
                saved_items.append(item)

        # Notify once for entire batch (silent visual banner, no haptic buzz)
        if is_batch and saved_items and hub and hub.connected:
            await hub.send_json({
                "cmd": "NOTIF",
                "app": "Memories",
                "title": "Memories Synced!",
                "body": f"{len(saved_items)} photos added"
            })

    else:
        # Direct raw binary body (e.g. Apple Shortcuts "Request Body: File" or cURL --data-binary)
        raw_bytes = await request.body()
        if raw_bytes and len(raw_bytes) > 50:
            fname = request.headers.get("x-filename") or "shortcut.jpg"
            item = await memories.ingest_bytes(
                raw_bytes,
                hub=hub,
                source=source,
                filename=fname,
                caption=caption,
                notify=True
            )
            if item:
                saved_items.append(item)

    if not saved_items:
        raise HTTPException(status_code=400, detail="No valid images received or image decoding failed")

    # Record nightly upload count
    if is_automated_sync and saved_items:
        memories.record_nightly_upload(len(saved_items))

    # If display was requested, push latest photo to ESP32 display
    if should_display or current_screen == "MEMORY":
        if current_screen != "MEMORY":
            await set_screen_mode("MEMORY")
        else:
            await show_memory_current()

    count = len(saved_items)
    replaced_count = sum(1 for p in saved_items if p.get("is_replaced"))
    quota_info = f"Quota: {len(memories.photos)}/{memories.max_photos}"
    if memories.nightly_quota > 0:
        quota_info += f", Nightly: {memories.get_nightly_upload_count()}/{memories.nightly_quota}"

    msg = f"Saved {count} photo{'s' if count > 1 else ''} to LUMO!"
    if replaced_count > 0:
        msg = f"Synced {count} photo{'s' if count > 1 else ''} ({replaced_count} duplicate{'s' if replaced_count > 1 else ''} replaced)!"
    msg += f" ({quota_info})"

    return {
        "ok": True,
        "status": "success",
        "count": count,
        "replaced_count": replaced_count,
        "message": msg,
        "photos": saved_items,
        "photo": saved_items[0],
        "nightly_used": memories.get_nightly_upload_count(),
        "nightly_quota": memories.nightly_quota,
        "total_count": len(memories.photos),
        "total_quota": memories.max_photos,
        "displayed": should_display or current_screen == "MEMORY"
    }

@app.post("/api/memories/upload")
async def upload_memory(request: Request):
    return await _process_memory_upload(request, default_source="upload", default_display=False)

@app.post("/api/memories/shortcut")
async def shortcut_upload_memory(request: Request):
    return await _process_memory_upload(request, default_source="apple_shortcut", default_display=False)

@app.post("/api/memories/next")
async def next_memory():
    _cancel_memory_timer()
    photo = await memories.next_photo(hub, on_advance=memories_auto_advance)
    if current_screen == "MEMORY" and memories.auto_rotate and not memories.is_gif_streaming():
        _start_memory_static_timer()
    return {"ok": True, "index": memories.current_index, "photo": photo}

@app.post("/api/memories/prev")
async def prev_memory():
    _cancel_memory_timer()
    photo = await memories.prev_photo(hub, on_advance=memories_auto_advance)
    if current_screen == "MEMORY" and memories.auto_rotate and not memories.is_gif_streaming():
        _start_memory_static_timer()
    return {"ok": True, "index": memories.current_index, "photo": photo}

@app.delete("/api/memories/{photo_id}")
async def delete_memory(photo_id: str):
    ok = memories.delete_photo(photo_id)
    if ok and current_screen == "MEMORY":
        await show_memory_current()
    return {"ok": ok}

@app.post("/api/memories/push")
async def push_memory_to_display(request: Request):
    touch_interaction()
    photo_id = request.query_params.get("id")
    if photo_id:
        memories.select_photo(photo_id)
    if current_screen != "MEMORY":
        await set_screen_mode("MEMORY")
    else:
        await show_memory_current()
    return {"ok": True}

@app.post("/api/memories/curate/scan")
async def scan_and_curate_library(request: Request):
    force = False
    try:
        data = await request.json()
        if isinstance(data, dict):
            force = bool(data.get("force", False))
    except Exception:
        pass
    if request.query_params.get("force", "").lower() in ("true", "1"):
        force = True
    counts = memories.scan_and_curate_all(force=force, reset_overrides=force)
    if current_screen == "MEMORY":
        await show_memory_current()
    return {
        "ok": True,
        "counts": counts,
        "curation_stats": memories.get_curation_stats(),
        "photos": memories.get_all_photos()
    }

@app.post("/api/memories/curate/override")
async def override_photo_category(item: CurationOverride):
    updated = memories.set_photo_category_override(item.id, item.category)
    if not updated:
        raise HTTPException(status_code=400, detail="Invalid photo ID or category (must be portrait, nature, other, or auto)")
    if current_screen == "MEMORY":
        await show_memory_current()
    return {"ok": True, "photo": updated, "curation_stats": memories.get_curation_stats()}

@app.post("/api/memories/config")
async def update_memories_config(item: MemoryConfig):
    if item.auto_rotate is not None:
        memories.auto_rotate = item.auto_rotate
    if item.interval_sec is not None:
        memories.interval_sec = max(5, item.interval_sec)
    if item.swap_bytes is not None:
        memories.swap_bytes = item.swap_bytes
    if item.bgr_mode is not None:
        memories.bgr_mode = item.bgr_mode
    if item.replace_duplicates is not None:
        memories.replace_duplicates = item.replace_duplicates
    if item.gif_loops is not None:
        memories.set_gif_loops(item.gif_loops)
    if item.curate_display is not None:
        memories.curate_display = item.curate_display
    if item.max_photos is not None or item.nightly_quota is not None:
        memories.set_quotas(item.max_photos, item.nightly_quota)
    if item.reset_nightly:
        memories.reset_tonight_uploads()
    memories._save_index()
    return {
        "ok": True,
        "auto_rotate": memories.auto_rotate,
        "interval_sec": memories.interval_sec,
        "swap_bytes": memories.swap_bytes,
        "bgr_mode": memories.bgr_mode,
        "replace_duplicates": memories.replace_duplicates,
        "gif_loops": memories.gif_loops,
        "curate_display": memories.curate_display,
        "curation_stats": memories.get_curation_stats(),
        "max_photos": memories.max_photos,
        "nightly_quota": memories.nightly_quota,
        "nightly_used": memories.get_nightly_upload_count(),
        "nightly_remaining": memories.get_nightly_remaining(),
    }

if __name__ == "__main__":
    import os
    import uvicorn
    from generate_ssl import generate_cert

    cert_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cert.pem")
    key_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "key.pem")

    enable_ssl = os.getenv("ENABLE_SSL", "true").lower() == "true"
    ssl_kwargs = {}

    if enable_ssl:
        if not (os.path.exists(cert_path) and os.path.exists(key_path)):
            try:
                logger.info("Auto-generating SSL certificate for mobile browser microphone access...")
                generate_cert(cert_path, key_path)
            except Exception as e:
                logger.warning(f"Could not auto-generate SSL cert: {e}")

        if os.path.exists(cert_path) and os.path.exists(key_path):
            logger.info(f"🔒 HTTPS enabled: cert={cert_path}, key={key_path}")
            logger.info(f"👉 Access dashboard securely at: https://<pi-ip>:{HTTP_PORT} (for phone mic & web UI)")
            logger.info(f"👉 Plain HTTP active on port {HTTP_PLAIN_PORT} at: http://<pi-ip>:{HTTP_PLAIN_PORT} (for Apple Shortcuts without SSL certificate errors)")
            ssl_kwargs["ssl_certfile"] = cert_path
            ssl_kwargs["ssl_keyfile"] = key_path
        else:
            logger.warning("Starting server in plain HTTP (client browser mic requires HTTPS)")
    else:
        logger.info("SSL disabled via ENABLE_SSL=false. Starting server in plain HTTP.")

    async def run_dual_servers():
        if enable_ssl and ssl_kwargs:
            # 1. Primary HTTPS server on 8080 (normal lifespan with WebSockets, Scheduler, Sage bridge)
            cfg_https = uvicorn.Config("main:app", host="0.0.0.0", port=HTTP_PORT, reload=False, **ssl_kwargs)
            srv_https = uvicorn.Server(cfg_https)

            # 2. Secondary Plain HTTP server on 8081 (lifespan off so no duplicate scheduler or websocket tasks)
            cfg_http = uvicorn.Config("main:app", host="0.0.0.0", port=HTTP_PLAIN_PORT, reload=False, lifespan="off")
            srv_http = uvicorn.Server(cfg_http)

            await asyncio.gather(srv_https.serve(), srv_http.serve())
        else:
            cfg = uvicorn.Config("main:app", host="0.0.0.0", port=HTTP_PORT, reload=False)
            srv = uvicorn.Server(cfg)
            await srv.serve()

    asyncio.run(run_dual_servers())
