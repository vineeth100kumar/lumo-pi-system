#include "ws_client.h"
#include "peripherals.h"
#include "animator.h"
#include "display.h"

#include <WiFi.h>
#include <ESPmDNS.h>
#include <ArduinoWebsockets.h>
#include <ArduinoJson.h>

using namespace websockets;

static WebsocketsClient ws;
static LumoState* statePtr = nullptr;
static bool isConnected = false;

static unsigned long lastReconnectAttempt = 0;
static unsigned long backoffMs = 2000;

static void handleTextMessage(const String& payload) {
  if (!statePtr) return;
  LumoState& s = *statePtr;

  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, payload);
  if (err) {
    Serial.println("[WS] JSON parse failed");
    return;
  }

  const char* cmd = doc["cmd"] | "";

  if (strcmp(cmd, "CLOCK") == 0) {
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
    const char* moodStr  = doc["mood"] | "NORMAL";
    const char* schedStr = doc["schedule"] | "AWAKE";

    LumoMood m = MOOD_NORMAL;
    if (strcmp(moodStr, "HAPPY") == 0)        m = MOOD_HAPPY;
    else if (strcmp(moodStr, "BORED") == 0)   m = MOOD_BORED;
    else if (strcmp(moodStr, "SAD") == 0)     m = MOOD_SAD;
    else if (strcmp(moodStr, "EXCITED") == 0) m = MOOD_EXCITED;

    CharSchedule sc = SCHED_AWAKE;
    if (strcmp(schedStr, "DROWSY") == 0)      sc = SCHED_DROWSY;
    else if (strcmp(schedStr, "SLEEP") == 0)  sc = SCHED_SLEEP;

    s.mood     = m;
    s.schedule = sc;
    animatorSetMood(m, sc);

    if (m == MOOD_EXCITED) {
      applyNeoPixels(NEO_COLOR, 80, 45); // Golden glow
    }
  }
  else if (strcmp(cmd, "LIGHTS") == 0) {
    const char* mStr = doc["mode"] | "WARM";
    NeoMode nm = NEO_WARM;
    if (strcmp(mStr, "COLOR") == 0)        nm = NEO_COLOR;
    else if (strcmp(mStr, "BREATHE") == 0) nm = NEO_BREATHE;
    else if (strcmp(mStr, "OFF") == 0)     nm = NEO_OFF;

    s.neo_mode       = nm;
    s.neo_brightness = doc["brightness"] | s.neo_brightness;
    s.neo_hue        = doc["hue"]        | s.neo_hue;
    applyNeoPixels(s.neo_mode, s.neo_brightness, s.neo_hue);
  }
  else if (strcmp(cmd, "HAPTIC") == 0) {
    uint16_t ms = doc["ms"] | 50;
    hapticPulse(ms);
  }
  else if (strcmp(cmd, "ALARM_RING") == 0) {
    s.alarm_ringing = true;
    s.next_screen   = SCREEN_ALARM;
    s.flag_screen_switch = true;
  }
  else if (strcmp(cmd, "ALARM_OFF") == 0) {
    s.alarm_ringing = false;
    s.next_screen   = SCREEN_FACE;
    s.flag_screen_switch = true;
    neoClear();
  }
  else if (strcmp(cmd, "SHOW_TASKS") == 0) {
    JsonArray arr = doc["items"].as<JsonArray>();
    s.task_count = 0;
    for (JsonVariant v : arr) {
      if (s.task_count < 5) {
        strncpy(s.tasks[s.task_count], v.as<const char*>(), sizeof(s.tasks[0]) - 1);
        s.task_count++;
      }
    }
    s.flag_tasks_changed = true;
  }
}

void wsInit(LumoState& state) {
  statePtr = &state;

  ws.onMessage([](WebsocketsMessage msg) {
    if (msg.isBinary()) {
      onNewArt((const uint8_t*)msg.c_str(), msg.length());
    } else if (msg.isText()) {
      handleTextMessage(msg.data());
    }
  });

  ws.onEvent([](WebsocketsEvent event, String data) {
    if (event == WebsocketsEvent::ConnectionOpened) {
      Serial.println("[WS] Connected to Pi 5!");
      isConnected = true;
      backoffMs = 2000;
      wsSend("{\"evt\":\"READY\",\"fw\":\"" FW_VERSION "\"}");
    } else if (event == WebsocketsEvent::ConnectionClosed) {
      Serial.println("[WS] Disconnected from Pi 5");
      isConnected = false;
    }
  });
}

void wsConnect() {
  if (WiFi.status() != WL_CONNECTED) return;

  Serial.println("[WS] Resolving Pi via mDNS (" PI_HOSTNAME ")...");
  IPAddress piIP;
  int n = MDNS.queryHost(PI_HOSTNAME);
  if (n > 0) {
    piIP = MDNS.IP(0);
    Serial.printf("[WS] Found Pi at %s\n", piIP.toString().c_str());
  } else {
    Serial.println("[WS] mDNS query failed. Trying direct host...");
    WiFi.hostByName(PI_HOSTNAME, piIP);
  }

  String url = "ws://" + (piIP.toString() != "0.0.0.0" ? piIP.toString() : String(PI_HOSTNAME)) + ":" + String(PI_WS_PORT) + PI_WS_PATH;
  Serial.printf("[WS] Connecting to %s\n", url.c_str());
  ws.connect(url);
}

void wsPoll() {
  ws.poll();

  if (!isConnected && millis() - lastReconnectAttempt > backoffMs) {
    lastReconnectAttempt = millis();
    Serial.printf("[WS] Reconnecting (backoff: %lu ms)...\n", backoffMs);
    wsConnect();
    backoffMs = min(backoffMs * 2, (unsigned long)30000);
  }
}

bool wsConnected() {
  return isConnected;
}

void wsSend(const char* json) {
  if (isConnected) {
    ws.send(json);
  }
}
