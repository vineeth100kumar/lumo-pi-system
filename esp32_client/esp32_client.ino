#include <Arduino.h>
#include <WiFi.h>
#include <ESPmDNS.h>

#include "config.h"
#include "peripherals.h"
#include "animator.h"
#include "display.h"
#include "ws_client.h"

static LumoState lumoState;
static ScreenMode currentScreen = SCREEN_CONNECTING;

const char* btnName(Button b) {
  switch (b) {
    case BTN_OK:    return "OK";
    case BTN_UP:    return "UP";
    case BTN_DOWN:  return "DOWN";
    case BTN_LEFT:  return "LEFT";
    case BTN_RIGHT: return "RIGHT";
    default:        return "NONE";
  }
}

void switchScreen(ScreenMode next) {
  currentScreen = next;
  displayDrawScreen(next, lumoState, true);
}

void handleButton(Button btn) {
  if (btn == BTN_NONE) return;

  hapticPulse(45);

  char json[64];
  snprintf(json, sizeof(json), "{\"evt\":\"BTN\",\"btn\":\"%s\"}", btnName(btn));
  wsSend(json);

  if (currentScreen == SCREEN_FACE) {
    if (btn == BTN_RIGHT) switchScreen(SCREEN_CLOCK);
    else if (btn == BTN_LEFT) switchScreen(SCREEN_TASKS);
    else if (btn == BTN_OK) switchScreen(SCREEN_SPOTIFY);
  }
  else if (currentScreen == SCREEN_CLOCK) {
    if (btn == BTN_LEFT) switchScreen(SCREEN_TASKS);
    else if (btn == BTN_OK) switchScreen(SCREEN_FACE);
    else if (btn == BTN_RIGHT) switchScreen(SCREEN_SPOTIFY);
  }
  else if (currentScreen == SCREEN_SPOTIFY) {
    if (btn == BTN_LEFT) switchScreen(SCREEN_CLOCK);
    else if (btn == BTN_RIGHT) switchScreen(SCREEN_FACE);
  }
  else if (currentScreen == SCREEN_TASKS) {
    if (btn == BTN_RIGHT || btn == BTN_LEFT) switchScreen(SCREEN_FACE);
  }
  else if (currentScreen == SCREEN_ALARM) {
    lumoState.alarm_ringing = false;
    neoClear();
    switchScreen(SCREEN_FACE);
  }
}

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println("\n--- LUMO ESP32-C3 DISPLAY NODE ---");

  ledcAttach(BUZZER_PIN, HAPTIC_FREQ, HAPTIC_RES);
  ledcWrite(BUZZER_PIN, 255);

  initNeoPixels();
  displayInit();

  displayDrawScreen(SCREEN_CONNECTING, lumoState, true);

  Serial.printf("[WIFI] Connecting to %s", WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  unsigned long startWifi = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - startWifi < 12000) {
    delay(300);
    Serial.print(".");
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("[WIFI] Connected! IP: %s\n", WiFi.localIP().toString().c_str());
    WiFi.setSleep(false);

    if (MDNS.begin("esp32-lumo")) {
      Serial.println("[MDNS] Started");
    }

    configTime(GMT_OFFSET_SEC, DAYLIGHT_OFFSET, NTP_SERVER1, NTP_SERVER2);
  } else {
    Serial.println("[WIFI] Connection failed. Will retry in loop.");
  }

  wsInit(lumoState);
  wsConnect();
  animatorInit();
}

void loop() {
  wsPoll();
  hapticUpdate();

  Button btn = readButton();
  handleButton(btn);

  animatorTick();

  if (!wsConnected()) {
    if (currentScreen != SCREEN_CONNECTING) {
      switchScreen(SCREEN_CONNECTING);
    }
    static unsigned long lastConnDraw = 0;
    if (millis() - lastConnDraw > 500) {
      lastConnDraw = millis();
      displayDrawScreen(SCREEN_CONNECTING, lumoState, false);
    }
    delay(10);
    return;
  } else if (currentScreen == SCREEN_CONNECTING) {
    switchScreen(SCREEN_FACE);
  }

  if (lumoState.flag_screen_switch) {
    lumoState.flag_screen_switch = false;
    switchScreen(lumoState.next_screen);
  }

  if (currentScreen == SCREEN_FACE) {
    if (animatorNeedsRedraw()) {
      displayDrawScreen(SCREEN_FACE, lumoState, false);
      animatorClearRedraw();
    }
    drawTimeBar(lumoState, false);
  }
  else if (currentScreen == SCREEN_CLOCK) {
    static int lastMin = -1;
    if (lumoState.m != lastMin) {
      lastMin = lumoState.m;
      displayDrawScreen(SCREEN_CLOCK, lumoState, false);
    }
  }
  else if (currentScreen == SCREEN_SPOTIFY) {
    static unsigned long lastProgressTick = 0;
    if (lumoState.sp_playing && millis() - lastProgressTick >= 500) {
      lastProgressTick = millis();
      lumoState.sp_progress_ms += 500;
      if (lumoState.sp_progress_ms > lumoState.sp_duration_ms) {
        lumoState.sp_progress_ms = lumoState.sp_duration_ms;
      }
      displayDrawScreen(SCREEN_SPOTIFY, lumoState, false);
    }
    if (lumoState.flag_spotify_changed || newArtReady) {
      lumoState.flag_spotify_changed = false;
      displayDrawScreen(SCREEN_SPOTIFY, lumoState, false);
    }
  }
  else if (currentScreen == SCREEN_TASKS) {
    if (lumoState.flag_tasks_changed) {
      lumoState.flag_tasks_changed = false;
      displayDrawScreen(SCREEN_TASKS, lumoState, true);
    }
  }
  else if (currentScreen == SCREEN_ALARM) {
    neoAlarmFlash();
    static unsigned long lastHapticPulse = 0;
    if (millis() - lastHapticPulse > 600) {
      lastHapticPulse = millis();
      hapticPulse(150);
    }
    static unsigned long lastAlarmDraw = 0;
    if (millis() - lastAlarmDraw > 300) {
      lastAlarmDraw = millis();
      displayDrawScreen(SCREEN_ALARM, lumoState, false);
    }
  }

  delay(6);
}
