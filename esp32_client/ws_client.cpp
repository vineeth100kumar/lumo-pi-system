#include <Arduino.h>
#include "ws_client.h"
#include "peripherals.h"
#include "animator.h"
#include "display.h"

#include <WiFi.h>
#include <ArduinoWebsockets.h>
#include <ArduinoJson.h>
#include <ESPmDNS.h>

using namespace websockets;

static WebsocketsClient client;
static LumoState* statePtr = nullptr;
static bool isConnected = false;

static unsigned long lastReconnectAttempt = 0;
static unsigned long reconnectInterval    = 2000;
static const unsigned long MAX_BACKOFF    = 30000;

static void handleTextMessage(const String& payload) {
  if (!statePtr) return;
  LumoState& s = *statePtr;

  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, payload);
  if (err) {
    Serial.printf("[WS] JSON parse error: %s\n", err.c_str());
    return;
  }

  const char* cmd = doc["cmd"] | "";

  if (strcmp(cmd, "SCREEN") == 0) {
    const char* m = doc["mode"] | "FACE";
    if (strcmp(m, "FACE") == 0)         s.next_screen = SCREEN_FACE;
    else if (strcmp(m, "CLOCK") == 0)   s.next_screen = SCREEN_CLOCK;
    else if (strcmp(m, "SYSTEM") == 0)  s.next_screen = SCREEN_SYSTEM;
    else if (strcmp(m, "SPOTIFY") == 0) s.next_screen = SCREEN_SPOTIFY;
    else if (strcmp(m, "TASKS") == 0)   s.next_screen = SCREEN_TASKS;
    s.flag_screen_switch = true;
    Serial.printf("[WS] Remote screen switch: %s\n", m);
  }
  else if (strcmp(cmd, "ANIM") == 0) {
    const char* animTypeStr = doc["type"] | "normal";
    int gx = doc["gaze_x"] | 0;
    int gy = doc["gaze_y"] | 0;
    unsigned long dur = doc["duration_ms"] | 2500;

    AnimType at = ANIM_NORMAL;
    if (strcmp(animTypeStr, "wink_left") == 0)   at = ANIM_WINK_L;
    else if (strcmp(animTypeStr, "wink_right") == 0) at = ANIM_WINK_R;
    else if (strcmp(animTypeStr, "heart") == 0)      at = ANIM_HEART;
    else if (strcmp(animTypeStr, "dance") == 0 || strcmp(animTypeStr, "music_dance") == 0) at = ANIM_DANCE;
    else if (strcmp(animTypeStr, "surprise") == 0)   at = ANIM_SURPRISE;
    else if (strcmp(animTypeStr, "happy") == 0)      at = ANIM_HAPPY;
    else if (strcmp(animTypeStr, "sleepy") == 0)     at = ANIM_SLEEPY;
    else if (strcmp(animTypeStr, "look") == 0)       at = ANIM_LOOK;

    s.anim_type = at;
    s.flag_anim_changed = true;
    animatorSetAnim(at, gx, gy, dur);
  }
  else if (strcmp(cmd, "EYE_COLOR") == 0) {
    uint16_t c565 = doc["rgb565"] | 0x077F;
    s.eye_color = c565;
    s.flag_anim_changed = true;
  }
  else if (strcmp(cmd, "NOTIF") == 0) {
    const char* app = doc["app"] | "iPhone";
    const char* title = doc["title"] | "Alert";
    const char* body = doc["body"] | "";
    strncpy(s.notif_app, app, sizeof(s.notif_app) - 1);
    strncpy(s.notif_title, title, sizeof(s.notif_title) - 1);
    strncpy(s.notif_body, body, sizeof(s.notif_body) - 1);
    s.notif_active = true;
    s.notif_start = millis();
    s.flag_anim_changed = true;
  }
  else if (strcmp(cmd, "SYSTEM_STATS") == 0) {
    s.cpu_temp = doc["cpu_temp"] | s.cpu_temp;
    s.cpu_pct  = doc["cpu_pct"]  | s.cpu_pct;
    s.ram_pct  = doc["ram_pct"]  | s.ram_pct;
    s.disk_pct = doc["disk_pct"] | s.disk_pct;
    s.flag_system_changed = true;
  }
  else if (strcmp(cmd, "CLOCK") == 0) {
    s.h = doc["h"] | s.h;
    s.m = doc["m"] | s.m;
    if (doc["weekday"].is<const char*>()) {
      strncpy(s.weekday, doc["weekday"], sizeof(s.weekday) - 1);
    }
    if (doc["date"].is<const char*>()) {
      strncpy(s.date, doc["date"], sizeof(s.date) - 1);
    }
  }
  else if (strcmp(cmd, "WEATHER") == 0) {
    s.temp_c = doc["temp_c"] | s.temp_c;
    if (doc["icon"].is<const char*>()) {
      strncpy(s.weather_icon, doc["icon"], sizeof(s.weather_icon) - 1);
    }
  }
  else if (strcmp(cmd, "SPOTIFY") == 0) {
    if (doc["title"].is<const char*>()) {
      strncpy(s.sp_title, doc["title"], sizeof(s.sp_title) - 1);
    }
    if (doc["artist"].is<const char*>()) {
      strncpy(s.sp_artist, doc["artist"], sizeof(s.sp_artist) - 1);
    }
    s.sp_progress_ms = doc["progress_ms"] | s.sp_progress_ms;
    s.sp_duration_ms = doc["duration_ms"] | s.sp_duration_ms;
    s.sp_playing     = doc["playing"]     | s.sp_playing;
    s.flag_spotify_changed = true;
  }
  else if (strcmp(cmd, "EMOTION") == 0) {
    const char* mStr = doc["mood"]     | "NORMAL";
    const char* sStr = doc["schedule"] | "AWAKE";

    LumoMood mood = MOOD_NORMAL;
    if (strcmp(mStr, "HAPPY")   == 0) mood = MOOD_HAPPY;
    else if (strcmp(mStr, "BORED")   == 0) mood = MOOD_BORED;
    else if (strcmp(mStr, "SAD")     == 0) mood = MOOD_SAD;
    else if (strcmp(mStr, "EXCITED") == 0) mood = MOOD_EXCITED;

    CharSchedule sched = SCHED_AWAKE;
    if (strcmp(sStr, "DROWSY") == 0) sched = SCHED_DROWSY;
    else if (strcmp(sStr, "SLEEP")  == 0) sched = SCHED_SLEEP;

    s.mood     = mood;
    s.schedule = sched;
    animatorSetMood(mood, sched);
  }
  else if (strcmp(cmd, "LIGHTS") == 0) {
    const char* modeStr = doc["mode"] | "WARM";
    uint8_t bri         = doc["brightness"] | 40;
    uint16_t hue        = doc["hue"] | 0;

    NeoMode nm = NEO_WARM;
    if (strcmp(modeStr, "COLOR")   == 0) nm = NEO_COLOR;
    else if (strcmp(modeStr, "BREATHE") == 0) nm = NEO_BREATHE;
    else if (strcmp(modeStr, "OFF")     == 0) nm = NEO_OFF;

    s.neo_mode       = nm;
    s.neo_brightness = bri;
    s.neo_hue        = hue;
    applyNeoPixels(nm, bri, hue);
  }
  else if (strcmp(cmd, "HAPTIC") == 0) {
    uint16_t ms = doc["ms"] | 50;
    hapticPulse(ms);
  }
  else if (strcmp(cmd, "ALARM_RING") == 0) {
    s.alarm_ringing = true;
  }
  else if (strcmp(cmd, "ALARM_OFF") == 0) {
    s.alarm_ringing = false;
    neoClear();
  }
  else if (strcmp(cmd, "SHOW_TASKS") == 0) {
    JsonArray arr = doc["items"];
    s.task_count = 0;
    for (const char* item : arr) {
      if (s.task_count < 5) {
        strncpy(s.tasks[s.task_count], item, 47);
        s.tasks[s.task_count][47] = '\0';
        s.task_count++;
      }
    }
    s.flag_tasks_changed = true;
  }
}

static void handleBinaryMessage(const uint8_t* data, size_t len) {
  onNewArt(data, len);
}

void wsInit(LumoState& state) {
  statePtr = &state;

  client.onMessage([](WebsocketsMessage msg) {
    if (msg.isText()) {
      handleTextMessage(msg.data());
    } else if (msg.isBinary()) {
      handleBinaryMessage((const uint8_t*)msg.c_str(), msg.length());
    }
  });

  client.onEvent([](WebsocketsEvent event, String data) {
    if (event == WebsocketsEvent::ConnectionOpened) {
      Serial.println("[WS] Connected to Pi server!");
      isConnected = true;
      reconnectInterval = 2000;
      char readyMsg[64];
      snprintf(readyMsg, sizeof(readyMsg), "{\"evt\":\"READY\",\"fw\":\"%s\"}", FW_VERSION);
      client.send(readyMsg);
    } else if (event == WebsocketsEvent::ConnectionClosed) {
      Serial.println("[WS] Disconnected from Pi server");
      isConnected = false;
    }
  });
}

void wsConnect() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[WS] WiFi not connected, skipping wsConnect");
    return;
  }

  String hostStr = PI_HOSTNAME;
  IPAddress piIP;
  if (!piIP.fromString(PI_HOSTNAME)) {
    IPAddress resolved = MDNS.queryHost(PI_HOSTNAME, 3000);
    if (resolved != INADDR_NONE && resolved[0] != 0) {
      hostStr = resolved.toString();
      Serial.printf("[WS] mDNS resolved: %s -> %s\n", PI_HOSTNAME, hostStr.c_str());
    } else {
      Serial.println("[WS] mDNS query failed. Trying direct hostname...");
    }
  } else {
    hostStr = piIP.toString();
  }

  Serial.printf("[WS] Connecting to ws://%s:%d%s\n", hostStr.c_str(), PI_WS_PORT, PI_WS_PATH);
  client.connect(hostStr, PI_WS_PORT, PI_WS_PATH);
}

void wsPoll() {
  client.poll();

  if (!isConnected && WiFi.status() == WL_CONNECTED) {
    unsigned long now = millis();
    if (now - lastReconnectAttempt >= reconnectInterval) {
      lastReconnectAttempt = now;
      Serial.printf("[WS] Reconnecting (backoff: %lu ms)...\n", reconnectInterval);
      wsConnect();
      reconnectInterval = min(reconnectInterval * 2, MAX_BACKOFF);
    }
  }
}

bool wsConnected() {
  return isConnected;
}

void wsSend(const char* json) {
  if (isConnected) {
    client.send(json);
  }
}
