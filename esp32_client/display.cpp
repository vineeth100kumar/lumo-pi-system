#include <Arduino.h>
#include "display.h"
#include "animator.h"
#include <Fonts/FreeSansBold24pt7b.h>
#include <Fonts/FreeSans12pt7b.h>
#include <Fonts/FreeSans9pt7b.h>
#include <math.h>

Adafruit_ILI9341 tft = Adafruit_ILI9341(TFT_CS, TFT_DC);

uint8_t artBuf[20004];
bool newArtReady = false;

static const uint16_t COLOR_BG_BLACK  = 0x0000;
static const uint16_t COLOR_BG_NAVY   = 0x1969;
static const uint16_t COLOR_TIME_BAR  = 0x08A3;
static const uint16_t COLOR_EYES      = 0xFD55;
static const uint16_t COLOR_SMILE     = 0xFDE0;
static const uint16_t COLOR_WHITE     = 0xFFFF;
static const uint16_t COLOR_MUTED     = 0x8C71;
static const uint16_t COLOR_ACCENT    = 0x2CDF;
static const uint16_t COLOR_GREEN     = 0x1DB4;
static const uint16_t COLOR_RED_PULSE = 0xD800;
static const uint16_t COLOR_RED_DARK  = 0x7800;

static int lastMinuteDrawn = -1;
static ScreenMode lastModeDrawn = SCREEN_CONNECTING;

void displayInit() {
  tft.begin();
  tft.setRotation(1);
  tft.setSPISpeed(40000000);
  tft.fillScreen(COLOR_BG_BLACK);
}

void onNewArt(const uint8_t* data, size_t len) {
  if (len >= 4 && data[0] == 0xAA && data[1] == 0xBB) {
    size_t copyLen = min(len - 4, (size_t)20000);
    memcpy(artBuf, data + 4, copyLen);
    newArtReady = true;
  }
}

static void fillSoftEllipse(int cx, int cy, int rx, int ry, uint16_t color) {
  for (int y = -ry; y <= ry; y++) {
    float xr = rx * sqrt(1.0f - (float)(y * y) / (ry * ry));
    int xi = (int)xr;
    tft.drawFastHLine(cx - xi, cy + y, 2 * xi, color);
  }
}

void drawProgressBar(int x, int y, int w, int h, float pct, uint16_t fillColor, uint16_t bgColor) {
  pct = constrain(pct, 0.0f, 1.0f);
  int fillW = (int)(w * pct);
  if (fillW > 0) {
    tft.fillRect(x, y, fillW, h, fillColor);
  }
  if (w - fillW > 0) {
    tft.fillRect(x + fillW, y, w - fillW, h, bgColor);
  }
}

void drawTimeBar(const LumoState& s, bool force) {
  if (!force && s.m == lastMinuteDrawn) return;
  lastMinuteDrawn = s.m;

  tft.fillRect(0, 200, 320, 40, COLOR_TIME_BAR);

  char timeBuf[16];
  uint8_t dispH = s.h % 12;
  if (dispH == 0) dispH = 12;
  snprintf(timeBuf, sizeof(timeBuf), "%02d:%02d %s", dispH, s.m, (s.h >= 12) ? "PM" : "AM");

  char dateBuf[24];
  snprintf(dateBuf, sizeof(dateBuf), "%s %s", s.weekday, s.date);

  tft.setTextSize(2);
  tft.setTextColor(COLOR_WHITE);
  tft.setCursor(12, 212);
  tft.print(timeBuf);

  tft.setTextColor(COLOR_MUTED);
  tft.setCursor(190, 212);
  tft.print(dateBuf);
}

static void drawFaceFull(const LumoState& s) {
  tft.fillScreen(COLOR_BG_NAVY);
  tft.fillRect(0, 0, 320, 32, tft.color565(15, 28, 50));
  tft.setTextSize(2);
  tft.setTextColor(COLOR_WHITE);
  int16_t x1, y1; uint16_t w, h;
  tft.getTextBounds("LUMO", 0, 0, &x1, &y1, &w, &h);
  tft.setCursor((320 - w) / 2, 8);
  tft.print("LUMO");
  tft.drawFastHLine(60, 31, 200, COLOR_MUTED);
  drawTimeBar(s, true);
}

static void drawFaceEyes(const LumoState& s) {
  int gaze = animatorGetEyeOffsetX();
  int lx = 115 + gaze;
  int rx = 205 + gaze;
  int y  = 85;

  tft.fillRect(80, 55, 160, 60, COLOR_BG_NAVY);

  if (animatorEyesOpen()) {
    fillSoftEllipse(lx, y, 16, 12, COLOR_EYES);
    fillSoftEllipse(rx, y, 16, 12, COLOR_EYES);
  } else {
    tft.fillRect(lx - 16, y - 2, 32, 4, COLOR_EYES);
    tft.fillRect(rx - 16, y - 2, 32, 4, COLOR_EYES);
  }

  tft.fillRect(110, 115, 100, 40, COLOR_BG_NAVY);

  if (animatorYawning()) {
    fillSoftEllipse(160, 130, 14, 18, COLOR_SMILE);
  } else if (animatorSmileVisible()) {
    if (s.mood == MOOD_SAD) {
      for (int x = -18; x <= 18; x++) {
        float dy = sqrt(18 * 18 - x * x) / 3.8f;
        tft.drawPixel(160 + x, 135 - (int)dy, COLOR_SMILE);
      }
    } else if (s.mood == MOOD_BORED) {
      tft.drawFastHLine(140, 128, 40, COLOR_SMILE);
    } else {
      for (int x = -20; x <= 20; x++) {
        float dy = sqrt(20 * 20 - x * x) / 3.8f;
        tft.drawPixel(160 + x, 122 + (int)dy, COLOR_SMILE);
      }
    }
  }
}

static void drawClockScreen(const LumoState& s, bool full) {
  if (full) {
    tft.fillScreen(COLOR_BG_BLACK);
    char wBuf[32];
    snprintf(wBuf, sizeof(wBuf), "%s %.1f C", s.weather_icon, s.temp_c);
    tft.setFont(&FreeSans9pt7b);
    tft.setTextColor(COLOR_MUTED);
    tft.setCursor(10, 20);
    tft.print(wBuf);

    tft.setCursor(250, 20);
    tft.print("LUMO");
    tft.drawFastHLine(0, 26, 320, tft.color565(40, 40, 40));

    tft.setCursor(35, 225);
    tft.print("<- Tasks     (OK) Face     Music ->");
  }

  tft.fillRect(30, 50, 260, 65, COLOR_BG_BLACK);
  char tBuf[16];
  snprintf(tBuf, sizeof(tBuf), "%02d:%02d", s.h, s.m);
  tft.setFont(&FreeSansBold24pt7b);
  tft.setTextColor(COLOR_WHITE);
  int16_t x1, y1; uint16_t w, h;
  tft.getTextBounds(tBuf, 0, 0, &x1, &y1, &w, &h);
  tft.setCursor((320 - w) / 2, 105);
  tft.print(tBuf);

  tft.fillRect(30, 125, 260, 28, COLOR_BG_BLACK);
  char dBuf[32];
  snprintf(dBuf, sizeof(dBuf), "%s, %s", s.weekday, s.date);
  tft.setFont(&FreeSans12pt7b);
  tft.setTextColor(COLOR_MUTED);
  tft.getTextBounds(dBuf, 0, 0, &x1, &y1, &w, &h);
  tft.setCursor((320 - w) / 2, 145);
  tft.print(dBuf);

  tft.fillRect(30, 160, 260, 25, COLOR_BG_BLACK);
  char aBuf[32];
  snprintf(aBuf, sizeof(aBuf), "ALARM  %02d:%02d", s.alarm_h, s.alarm_m);
  tft.setFont(&FreeSans9pt7b);
  tft.setTextColor(COLOR_ACCENT);
  tft.getTextBounds(aBuf, 0, 0, &x1, &y1, &w, &h);
  tft.setCursor((320 - w) / 2, 180);
  tft.print(aBuf);
}

static void drawSpotifyScreen(const LumoState& s, bool full) {
  if (full) {
    tft.fillScreen(COLOR_BG_BLACK);
    tft.setFont(&FreeSans9pt7b);
    tft.setTextColor(COLOR_GREEN);
    tft.setCursor(10, 20);
    tft.print("Spotify Now Playing");
    tft.drawFastHLine(0, 26, 320, tft.color565(30, 30, 30));

    tft.setTextColor(COLOR_MUTED);
    tft.setCursor(25, 225);
    tft.print("<- Clock    (OK) Play/Pause    Face ->");
  }

  if (newArtReady || full) {
    tft.drawRGBBitmap(10, 36, (uint16_t*)artBuf, 100, 100);
    newArtReady = false;
  }

  tft.fillRect(120, 36, 195, 65, COLOR_BG_BLACK);
  tft.setFont(&FreeSans12pt7b);
  tft.setTextColor(COLOR_WHITE);
  tft.setCursor(120, 60);

  char titleCut[18];
  strncpy(titleCut, s.sp_title, 17);
  titleCut[17] = '\0';
  tft.print(strlen(titleCut) > 0 ? titleCut : "No Track");

  tft.setFont(&FreeSans9pt7b);
  tft.setTextColor(COLOR_MUTED);
  tft.setCursor(120, 85);
  char artistCut[22];
  strncpy(artistCut, s.sp_artist, 21);
  artistCut[21] = '\0';
  tft.print(strlen(artistCut) > 0 ? artistCut : "Idle");

  float pct = (s.sp_duration_ms > 0) ? ((float)s.sp_progress_ms / s.sp_duration_ms) : 0.0f;
  drawProgressBar(20, 155, 280, 8, pct, COLOR_GREEN, tft.color565(50, 50, 50));

  tft.fillRect(20, 170, 280, 20, COLOR_BG_BLACK);
  char progBuf[16], durBuf[16];
  uint32_t pSec = s.sp_progress_ms / 1000;
  uint32_t dSec = s.sp_duration_ms / 1000;
  snprintf(progBuf, sizeof(progBuf), "%d:%02d", pSec / 60, pSec % 60);
  snprintf(durBuf, sizeof(durBuf), "%d:%02d", dSec / 60, dSec % 60);

  tft.setFont(&FreeSans9pt7b);
  tft.setTextColor(COLOR_MUTED);
  tft.setCursor(20, 185);
  tft.print(progBuf);

  int16_t x1, y1; uint16_t w, h;
  tft.getTextBounds(durBuf, 0, 0, &x1, &y1, &w, &h);
  tft.setCursor(300 - w, 185);
  tft.print(durBuf);
}

static void drawTasksScreen(const LumoState& s) {
  tft.fillScreen(COLOR_BG_BLACK);
  tft.setFont(&FreeSans9pt7b);
  tft.setTextColor(COLOR_WHITE);
  tft.setCursor(10, 20);
  tft.print("Tasks");
  tft.drawFastHLine(0, 26, 320, tft.color565(40, 40, 40));

  int y = 55;
  for (int i = 0; i < s.task_count && i < 5; i++) {
    tft.setTextColor(COLOR_ACCENT);
    tft.setCursor(15, y);
    tft.print("[ ] ");
    tft.setTextColor(COLOR_WHITE);
    tft.print(s.tasks[i]);
    y += 28;
  }

  if (s.task_count == 0) {
    tft.setTextColor(COLOR_MUTED);
    tft.setCursor(30, 90);
    tft.print("All tasks completed!");
  }

  tft.setFont(&FreeSans9pt7b);
  tft.setTextColor(COLOR_MUTED);
  tft.setCursor(35, 225);
  tft.print("<- Face               (OK) Toggle");
}

static void drawAlarmScreen(const LumoState& s) {
  static bool invert = false;
  invert = !invert;

  tft.fillScreen(invert ? COLOR_RED_PULSE : COLOR_RED_DARK);
  tft.setTextColor(COLOR_WHITE);

  tft.setTextSize(3);
  int16_t x1, y1; uint16_t w, h;
  tft.getTextBounds("WAKE UP!", 0, 0, &x1, &y1, &w, &h);
  tft.setCursor((320 - w) / 2, 40);
  tft.print("WAKE UP!");

  char aBuf[16];
  snprintf(aBuf, sizeof(aBuf), "%02d:%02d", s.alarm_h, s.alarm_m);
  tft.setFont(&FreeSansBold24pt7b);
  tft.getTextBounds(aBuf, 0, 0, &x1, &y1, &w, &h);
  tft.setCursor((320 - w) / 2, 130);
  tft.print(aBuf);

  tft.setFont(&FreeSans12pt7b);
  const char* hint = "PRESS ANY BUTTON";
  tft.getTextBounds(hint, 0, 0, &x1, &y1, &w, &h);
  tft.setCursor((320 - w) / 2, 190);
  tft.print(hint);
}

static void drawConnectingScreen(const LumoState& s) {
  static int dotCount = 0;
  dotCount = (dotCount + 1) % 4;

  tft.fillScreen(tft.color565(10, 15, 25));
  tft.setFont(&FreeSans12pt7b);
  tft.setTextColor(COLOR_WHITE);

  char cBuf[32];
  snprintf(cBuf, sizeof(cBuf), "Connecting to Pi%s",
           dotCount == 1 ? "." : (dotCount == 2 ? ".." : (dotCount == 3 ? "..." : "")));

  int16_t x1, y1; uint16_t w, h;
  tft.getTextBounds("Connecting to Pi...", 0, 0, &x1, &y1, &w, &h);
  tft.setCursor((320 - w) / 2, 110);
  tft.print(cBuf);

  tft.setFont(&FreeSans9pt7b);
  tft.setTextColor(COLOR_MUTED);
  tft.setCursor(70, 150);
  tft.print("ws://lumo.local:8765");
}

void displayDrawScreen(ScreenMode mode, const LumoState& s, bool forceFullRedraw) {
  bool modeChanged = (mode != lastModeDrawn) || forceFullRedraw;
  lastModeDrawn = mode;

  switch (mode) {
    case SCREEN_FACE:
      if (modeChanged) drawFaceFull(s);
      drawFaceEyes(s);
      break;
    case SCREEN_CLOCK:
      drawClockScreen(s, modeChanged);
      break;
    case SCREEN_SPOTIFY:
      drawSpotifyScreen(s, modeChanged);
      break;
    case SCREEN_TASKS:
      drawTasksScreen(s);
      break;
    case SCREEN_ALARM:
      drawAlarmScreen(s);
      break;
    case SCREEN_CONNECTING:
      drawConnectingScreen(s);
      break;
  }
}
