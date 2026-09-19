#include <Arduino.h>
#include "display.h"
#include "animator.h"
#include <math.h>

Adafruit_ILI9341 tft = Adafruit_ILI9341(TFT_CS, TFT_DC);

uint8_t artBuf[20004];
bool newArtReady = false;

static const uint16_t COLOR_BG_BLACK  = 0x0000;
static const uint16_t COLOR_BG_NAVY   = 0x11AB; // tft.color565(18, 30, 55)
static const uint16_t COLOR_HEADER    = 0x11EB; // tft.color565(18, 30, 55)
static const uint16_t COLOR_TIME_BAR  = 0x08A3; // tft.color565(12, 15, 25)
static const uint16_t COLOR_EYES      = 0xFD55; // Soft warm pink
static const uint16_t COLOR_SMILE     = 0xFDE0; // Warm soft smile
static const uint16_t COLOR_WHITE     = 0xFFFF;
static const uint16_t COLOR_MUTED     = 0x7BEF; // tft.color565(120, 125, 125)
static const uint16_t COLOR_ACCENT    = 0x2BDF; // Light blue
static const uint16_t COLOR_GREEN     = 0x1DB4; // Spotify green
static const uint16_t COLOR_RED_PULSE = 0xD800; // Alarm red
static const uint16_t COLOR_RED_DARK  = 0x7800;

static int lastMinuteDrawn = -1;
static ScreenMode lastModeDrawn = SCREEN_CONNECTING;

void displayInit() {
  tft.begin();
  tft.setRotation(1); // Landscape 320x240
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
  if (rx == 14 && ry == 10) {
    static int8_t eyeX[11];
    static bool init = false;
    if (!init) {
      for (int y = 0; y <= 10; y++) {
        eyeX[y] = (int8_t)(14 * sqrt(1.0f - (float)(y * y) / 100.0f));
      }
      init = true;
    }
    for (int y = -10; y <= 10; y++) {
      int xi = eyeX[abs(y)];
      tft.drawFastHLine(cx - xi, cy + y, 2 * xi, color);
    }
    return;
  }

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
  snprintf(timeBuf, sizeof(timeBuf), "%d:%02d %s", dispH, s.m, (s.h >= 12) ? "PM" : "AM");

  char dateBuf[24];
  snprintf(dateBuf, sizeof(dateBuf), "%s %s", s.weekday, s.date);

  tft.setFont(NULL);
  tft.setTextSize(2);
  tft.setTextColor(COLOR_WHITE);
  tft.setCursor(14, 212);
  tft.print(timeBuf);

  tft.setTextColor(COLOR_MUTED);
  tft.setCursor(200, 212);
  tft.print(dateBuf);
}

static void drawFaceFull(const LumoState& s) {
  tft.fillScreen(COLOR_BG_NAVY);

  tft.fillRect(0, 0, 320, 38, COLOR_HEADER);
  tft.setFont(NULL);
  tft.setTextSize(2);
  tft.setTextColor(COLOR_WHITE);
  int16_t x1, y1; uint16_t w, h;
  tft.getTextBounds("LUMO", 0, 0, &x1, &y1, &w, &h);
  tft.setCursor((320 - w) / 2, 10);
  tft.print("LUMO");
  tft.drawFastHLine(60, 36, 200, COLOR_MUTED);

  for (int i = 0; i < 6; i++) {
    tft.drawFastHLine(40 + i, 190 + i, 240 - (i * 2), tft.color565(30, 60, 110));
  }

  drawTimeBar(s, true);
}

static void drawFaceEyes(const LumoState& s) {
  int gaze = animatorGetEyeOffsetX();
  int lx = 135 + gaze;
  int rx = 185 + gaze;
  int y  = 88;

  tft.fillRect(90, 50, 180, 58, COLOR_BG_NAVY);

  if (animatorEyesOpen()) {
    fillSoftEllipse(lx, y, 14, 10, COLOR_EYES);
    fillSoftEllipse(rx, y, 14, 10, COLOR_EYES);
  } else {
    tft.fillRect(lx - 14, y, 28, 4, COLOR_EYES);
    tft.fillRect(rx - 14, y, 28, 4, COLOR_EYES);
  }

  tft.fillRect(115, 112, 90, 35, COLOR_BG_NAVY);

  if (animatorYawning()) {
    fillSoftEllipse(160, 126, 10, 14, COLOR_SMILE);
  } else if (animatorSmileVisible()) {
    int cx = 160, cy = 125, r = 22;
    if (s.mood == MOOD_SAD) {
      for (int x = -r; x <= r; x++) {
        int dy = (int)(sqrt(r * r - x * x) / 4.5f);
        tft.drawPixel(cx + x, cy + 10 - dy, COLOR_SMILE);
      }
    } else if (s.mood == MOOD_BORED) {
      tft.drawFastHLine(cx - 16, cy + 4, 32, COLOR_SMILE);
    } else {
      for (int x = -r; x <= r; x++) {
        int dy = (int)(sqrt(r * r - x * x) / 4.5f);
        tft.drawPixel(cx + x, cy + dy, COLOR_SMILE);
      }
    }
  }
}

static void drawClockScreen(const LumoState& s, bool full) {
  tft.setFont(NULL);

  if (full) {
    tft.fillScreen(COLOR_BG_BLACK);

    char wBuf[32];
    snprintf(wBuf, sizeof(wBuf), "%.1f C  %s", s.temp_c, s.weather_icon);
    tft.setTextSize(2);
    tft.setTextColor(COLOR_MUTED);
    tft.setCursor(12, 10);
    tft.print(wBuf);

    tft.setTextColor(COLOR_WHITE);
    tft.setCursor(255, 10);
    tft.print("LUMO");
    tft.drawFastHLine(10, 34, 300, tft.color565(50, 50, 60));

    tft.setTextSize(1);
    tft.setTextColor(COLOR_MUTED);
    tft.setCursor(40, 218);
    tft.print("Controlled via Local Web Dashboard");
  }

  tft.fillRect(20, 52, 280, 55, COLOR_BG_BLACK);
  char tBuf[16];
  snprintf(tBuf, sizeof(tBuf), "%02d:%02d", s.h, s.m);
  tft.setTextSize(6);
  tft.setTextColor(COLOR_WHITE);
  int16_t x1, y1; uint16_t w, h;
  tft.getTextBounds(tBuf, 0, 0, &x1, &y1, &w, &h);
  tft.setCursor((320 - w) / 2, 54);
  tft.print(tBuf);

  tft.fillRect(20, 118, 280, 24, COLOR_BG_BLACK);
  char dBuf[32];
  snprintf(dBuf, sizeof(dBuf), "%s, %s", s.weekday, s.date);
  tft.setTextSize(2);
  tft.setTextColor(COLOR_MUTED);
  tft.getTextBounds(dBuf, 0, 0, &x1, &y1, &w, &h);
  tft.setCursor((320 - w) / 2, 120);
  tft.print(dBuf);

  tft.fillRect(20, 155, 280, 24, COLOR_BG_BLACK);
  char aBuf[32];
  snprintf(aBuf, sizeof(aBuf), "ALARM  %02d:%02d", s.alarm_h, s.alarm_m);
  tft.setTextSize(2);
  tft.setTextColor(COLOR_ACCENT);
  tft.getTextBounds(aBuf, 0, 0, &x1, &y1, &w, &h);
  tft.setCursor((320 - w) / 2, 156);
  tft.print(aBuf);
}

// SCREEN: SYSTEM VITALS (Raspberry Pi 5 Status)
static void drawSystemScreen(const LumoState& s, bool full) {
  tft.setFont(NULL);

  if (full) {
    tft.fillScreen(COLOR_BG_BLACK);
    tft.setTextSize(2);
    tft.setTextColor(COLOR_ACCENT);
    tft.setCursor(12, 10);
    tft.print("Raspberry Pi 5 Vitals");
    tft.drawFastHLine(10, 32, 300, tft.color565(50, 50, 60));

    tft.setTextSize(1);
    tft.setTextColor(COLOR_MUTED);
    tft.setCursor(65, 220);
    tft.print("Controlled via Web Dashboard");
  }

  // CPU Temp
  tft.fillRect(14, 42, 292, 18, COLOR_BG_BLACK);
  tft.setTextSize(2);
  tft.setTextColor(COLOR_WHITE);
  tft.setCursor(14, 42);
  tft.printf("CPU Temp: %.1f C", s.cpu_temp);
  drawProgressBar(14, 64, 292, 8, s.cpu_temp / 85.0f, (s.cpu_temp > 70.0f ? COLOR_RED_PULSE : COLOR_ACCENT), tft.color565(40, 40, 50));

  // CPU Load
  tft.fillRect(14, 82, 292, 18, COLOR_BG_BLACK);
  tft.setCursor(14, 82);
  tft.printf("CPU Load: %d%%", s.cpu_pct);
  drawProgressBar(14, 104, 292, 8, s.cpu_pct / 100.0f, COLOR_GREEN, tft.color565(40, 40, 50));

  // RAM Usage
  tft.fillRect(14, 122, 292, 18, COLOR_BG_BLACK);
  tft.setCursor(14, 122);
  tft.printf("RAM:      %d%%", s.ram_pct);
  drawProgressBar(14, 144, 292, 8, s.ram_pct / 100.0f, COLOR_ACCENT, tft.color565(40, 40, 50));

  // Disk Storage
  tft.fillRect(14, 162, 292, 18, COLOR_BG_BLACK);
  tft.setCursor(14, 162);
  tft.printf("Disk:     %d%%", s.disk_pct);
  drawProgressBar(14, 184, 292, 8, s.disk_pct / 100.0f, COLOR_MUTED, tft.color565(40, 40, 50));
}

static void drawSpotifyScreen(const LumoState& s, bool full) {
  tft.setFont(NULL);

  if (full) {
    tft.fillScreen(COLOR_BG_BLACK);

    tft.setTextSize(2);
    tft.setTextColor(COLOR_GREEN);
    tft.setCursor(12, 10);
    tft.print("Now Playing");

    tft.setTextColor(COLOR_MUTED);
    tft.setCursor(255, 10);
    tft.print("LUMO");
    tft.drawFastHLine(10, 32, 300, tft.color565(40, 40, 50));

    tft.setTextSize(1);
    tft.setCursor(30, 218);
    tft.print("Controlled via Local Web Dashboard");
  }

  if (newArtReady || full) {
    tft.drawRect(10, 42, 104, 104, tft.color565(60, 60, 70));
    tft.drawRGBBitmap(12, 44, (uint16_t*)artBuf, 100, 100);
    newArtReady = false;
  }

  tft.fillRect(122, 42, 195, 104, COLOR_BG_BLACK);

  tft.setTextSize(2);
  tft.setTextColor(COLOR_WHITE);
  tft.setCursor(124, 46);
  char titleCut[16];
  strncpy(titleCut, s.sp_title, 15);
  titleCut[15] = '\0';
  tft.print(strlen(titleCut) > 0 ? titleCut : "No Track");

  tft.setTextColor(COLOR_MUTED);
  tft.setCursor(124, 72);
  char artistCut[16];
  strncpy(artistCut, s.sp_artist, 15);
  artistCut[15] = '\0';
  tft.print(strlen(artistCut) > 0 ? artistCut : "Idle");

  tft.setTextSize(1);
  tft.setTextColor(COLOR_WHITE);
  tft.setCursor(124, 108);
  char progBuf[16], durBuf[16];
  uint32_t pSec = s.sp_progress_ms / 1000;
  uint32_t dSec = s.sp_duration_ms / 1000;
  snprintf(progBuf, sizeof(progBuf), "%d:%02d", pSec / 60, pSec % 60);
  snprintf(durBuf, sizeof(durBuf), "%d:%02d", dSec / 60, dSec % 60);
  tft.printf("%s / %s", progBuf, durBuf);

  tft.setTextColor(s.sp_playing ? COLOR_GREEN : COLOR_MUTED);
  tft.setCursor(124, 126);
  tft.print(s.sp_playing ? "[PLAYING]" : "[PAUSED]");

  float pct = (s.sp_duration_ms > 0) ? ((float)s.sp_progress_ms / s.sp_duration_ms) : 0.0f;
  drawProgressBar(12, 162, 296, 8, pct, COLOR_GREEN, tft.color565(40, 40, 40));
}

static void drawTasksScreen(const LumoState& s) {
  tft.setFont(NULL);
  tft.fillScreen(COLOR_BG_BLACK);

  tft.setTextSize(2);
  tft.setTextColor(COLOR_WHITE);
  tft.setCursor(12, 10);
  tft.print("Tasks");
  tft.drawFastHLine(10, 32, 300, tft.color565(50, 50, 60));

  int y = 48;
  for (int i = 0; i < s.task_count && i < 5; i++) {
    tft.setTextSize(2);
    tft.setTextColor(COLOR_ACCENT);
    tft.setCursor(14, y);
    tft.print("[ ] ");

    tft.setTextColor(COLOR_WHITE);
    char cut[22];
    strncpy(cut, s.tasks[i], 21);
    cut[21] = '\0';
    tft.print(cut);
    y += 28;
  }

  if (s.task_count == 0) {
    tft.setTextSize(2);
    tft.setTextColor(COLOR_MUTED);
    tft.setCursor(35, 90);
    tft.print("All tasks done!");
  }

  tft.setTextSize(1);
  tft.setTextColor(COLOR_MUTED);
  tft.setCursor(65, 218);
  tft.print("Controlled via Web Dashboard");
}

static void drawAlarmScreen(const LumoState& s) {
  static bool invert = false;
  invert = !invert;

  tft.setFont(NULL);
  tft.fillScreen(invert ? COLOR_RED_PULSE : COLOR_RED_DARK);
  tft.setTextColor(COLOR_WHITE);

  tft.setTextSize(3);
  int16_t x1, y1; uint16_t w, h;
  tft.getTextBounds("WAKE UP!", 0, 0, &x1, &y1, &w, &h);
  tft.setCursor((320 - w) / 2, 35);
  tft.print("WAKE UP!");

  char aBuf[16];
  snprintf(aBuf, sizeof(aBuf), "%02d:%02d", s.alarm_h, s.alarm_m);
  tft.setTextSize(6);
  tft.getTextBounds(aBuf, 0, 0, &x1, &y1, &w, &h);
  tft.setCursor((320 - w) / 2, 85);
  tft.print(aBuf);

  tft.setTextSize(2);
  const char* hint = "TAP DISMISS IN WEB UI";
  tft.getTextBounds(hint, 0, 0, &x1, &y1, &w, &h);
  tft.setCursor((320 - w) / 2, 175);
  tft.print(hint);
}

static void drawConnectingScreen(const LumoState& s) {
  static int dotCount = 0;
  dotCount = (dotCount + 1) % 4;

  tft.setFont(NULL);
  tft.fillScreen(COLOR_BG_NAVY);

  fillSoftEllipse(135, 75, 14, 10, COLOR_EYES);
  fillSoftEllipse(185, 75, 14, 10, COLOR_EYES);
  tft.drawFastHLine(148, 105, 24, COLOR_SMILE);

  char cBuf[32];
  snprintf(cBuf, sizeof(cBuf), "Connecting to Pi%s",
           dotCount == 1 ? "." : (dotCount == 2 ? ".." : (dotCount == 3 ? "..." : "")));

  tft.setTextSize(2);
  tft.setTextColor(COLOR_WHITE);
  int16_t x1, y1; uint16_t w, h;
  tft.getTextBounds("Connecting to Pi...", 0, 0, &x1, &y1, &w, &h);
  tft.setCursor((320 - w) / 2, 135);
  tft.print(cBuf);

  tft.setTextSize(1);
  tft.setTextColor(COLOR_MUTED);
  char ipBuf[40];
  snprintf(ipBuf, sizeof(ipBuf), "Target: %s:%d", PI_HOSTNAME, PI_WS_PORT);
  tft.getTextBounds(ipBuf, 0, 0, &x1, &y1, &w, &h);
  tft.setCursor((320 - w) / 2, 170);
  tft.print(ipBuf);
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
    case SCREEN_SYSTEM:
      drawSystemScreen(s, modeChanged);
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
