#include <Arduino.h>
#include <WiFi.h>
#include <time.h>
#include "config.h"
#include "peripherals.h"
#include "animator.h"
#include "display.h"
#include "ws_client.h"

static LumoState lumoState;
static ScreenMode currentScreen = SCREEN_CONNECTING;

void switchScreen(ScreenMode next) {
  currentScreen = next;
  displayDrawScreen(next, lumoState, true);
}

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println("\n=== LUMO Companion Firmware v1.2.0 Starting ===");

  ledcAttach(BUZZER_PIN, HAPTIC_FREQ, HAPTIC_RES);
  ledcWrite(BUZZER_PIN, 255);

  initNeoPixels();
  displayInit();

  tft.setFont(NULL);
  tft.setTextSize(2);
  tft.setTextColor(0xFFFF);
  tft.setCursor(20, 100);
  tft.print("Connecting to Wi-Fi...");

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  unsigned long startAttempt = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - startAttempt < 10000) {
    delay(250);
    Serial.print(".");
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("[WiFi] Connected! IP: %s\n", WiFi.localIP().toString().c_str());
    configTime(GMT_OFFSET_SEC, DAYLIGHT_OFFSET, NTP_SERVER1, NTP_SERVER2);
    WiFi.setSleep(false);
  } else {
    Serial.println("[WiFi] Connection failed, continuing offline...");
  }

  wsInit(lumoState);
  wsConnect();
  animatorInit();

  currentScreen = SCREEN_CONNECTING;
  displayDrawScreen(SCREEN_CONNECTING, lumoState, true);
}

void loop() {
  wsPoll();
  hapticUpdate();

  // Button ladder read (optional, sends events if pressed)
  Button btn = readButton();
  if (btn != BTN_NONE) {
    hapticPulse(45);
    char json[64];
    const char* bName = (btn == BTN_OK ? "OK" : (btn == BTN_UP ? "UP" : (btn == BTN_DOWN ? "DOWN" : (btn == BTN_LEFT ? "LEFT" : "RIGHT"))));
    snprintf(json, sizeof(json), "{\"evt\":\"BTN\",\"btn\":\"%s\"}", bName);
    wsSend(json);
  }

  animatorTick();

  // Transition from CONNECTING to FACE once Pi sends data or connects
  if (currentScreen == SCREEN_CONNECTING && wsConnected()) {
    switchScreen(SCREEN_FACE);
  }

  // Handle alarm triggered from Pi
  if (lumoState.alarm_ringing && currentScreen != SCREEN_ALARM) {
    switchScreen(SCREEN_ALARM);
  } else if (!lumoState.alarm_ringing && currentScreen == SCREEN_ALARM) {
    switchScreen(SCREEN_FACE);
  }

  // Handle remote screen switch command from Web Page
  if (lumoState.flag_screen_switch) {
    lumoState.flag_screen_switch = false;
    switchScreen(lumoState.next_screen);
  }

  // Screen-specific updates
  if (currentScreen == SCREEN_FACE) {
    if (animatorNeedsRedraw() || lumoState.flag_anim_changed) {
      displayDrawScreen(SCREEN_FACE, lumoState, false);
      animatorClearRedraw();
      lumoState.flag_anim_changed = false;
    }
    drawTimeBar(lumoState, false);
  }
  else if (currentScreen == SCREEN_CLOCK) {
    static int lastM = -1;
    if (lumoState.m != lastM) {
      lastM = lumoState.m;
      displayDrawScreen(SCREEN_CLOCK, lumoState, false);
    }
  }
  else if (currentScreen == SCREEN_SYSTEM) {
    if (lumoState.flag_system_changed) {
      lumoState.flag_system_changed = false;
      displayDrawScreen(SCREEN_SYSTEM, lumoState, false);
    }
  }
  else if (currentScreen == SCREEN_SPOTIFY) {
    static unsigned long lastProgressTick = 0;
    if (lumoState.sp_playing && millis() - lastProgressTick >= 500) {
      lastProgressTick = millis();
      lumoState.sp_progress_ms = min(lumoState.sp_progress_ms + 500, lumoState.sp_duration_ms);
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
      displayDrawScreen(SCREEN_TASKS, lumoState, false);
    }
  }
  else if (currentScreen == SCREEN_ALARM) {
    static unsigned long lastAlarmTick = 0;
    if (millis() - lastAlarmTick >= 500) {
      lastAlarmTick = millis();
      neoAlarmFlash();
      hapticPulse(80);
      displayDrawScreen(SCREEN_ALARM, lumoState, false);
    }
  }
  else if (currentScreen == SCREEN_CONNECTING) {
    static unsigned long lastConnTick = 0;
    if (millis() - lastConnTick >= 600) {
      lastConnTick = millis();
      displayDrawScreen(SCREEN_CONNECTING, lumoState, false);
    }
  }

  delay(12);
}
