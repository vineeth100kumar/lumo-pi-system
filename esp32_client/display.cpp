#include <Arduino.h>
#include "display.h"
#include "animator.h"
#include <math.h>

Adafruit_ILI9341 tft = Adafruit_ILI9341(TFT_CS, TFT_DC);

uint8_t artBuf[20004];
bool newArtReady = false;

static const uint16_t COLOR_BG_BLACK  = 0x0000;
static const uint16_t COLOR_BG_STEALTH= 0x0842; // Deep stealth black/navy
static const uint16_t COLOR_HEADER    = 0x0842;
static const uint16_t COLOR_TIME_BAR  = 0x0000;
static const uint16_t COLOR_WHITE     = 0xFFFF;
static const uint16_t COLOR_MUTED     = 0x632C; // Slate gray
static const uint16_t COLOR_ACCENT    = 0x073F; // Electric Cyan
static const uint16_t COLOR_GREEN     = 0x07E6; // Matrix Green
static const uint16_t COLOR_RED_PULSE = 0xF8A4; // Tactical Red
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

  tft.fillRect(0, 204, 320, 36, COLOR_TIME_BAR);
  tft.drawFastHLine(20, 204, 280, tft.color565(30, 35, 45));

  char timeBuf[16];
  uint8_t dispH = s.h % 12;
  if (dispH == 0) dispH = 12;
  snprintf(timeBuf, sizeof(timeBuf), "%d:%02d %s", dispH, s.m, (s.h >= 12) ? "PM" : "AM");

  char dateBuf[24];
  snprintf(dateBuf, sizeof(dateBuf), "%s %s", s.weekday, s.date);

  tft.setFont(NULL);
  tft.setTextSize(2);
  tft.setTextColor(COLOR_WHITE);
  tft.setCursor(20, 214);
  tft.print(timeBuf);

  tft.setTextColor(COLOR_MUTED);
  tft.setCursor(195, 214);
  tft.print(dateBuf);
}

// Sleek Cybernetic Eye (56x48px, r=8, determined angular brow)
static void drawCyberEye(int cx, int cy, int w, int h, int r, float eyelid, uint16_t color, bool isLeft, int browSlant, bool isStandby) {
  if (isStandby || eyelid <= 0.12f) {
    // Sleek horizontal low-power visor slit (---)
    tft.fillRoundRect(cx - w/2, cy - 3, w, 6, 2, color);
    return;
  }

  // Base Visor Rectangle with beveled/rounded corners
  tft.fillRoundRect(cx - w/2, cy - h/2, w, h, r, color);

  // Eyelid masking from top (smooth shutter blink)
  if (eyelid < 0.95f) {
    int clipH = (int)(h * (1.0f - eyelid));
    tft.fillRect(cx - w/2 - 2, cy - h/2 - 2, w + 4, clipH + 2, COLOR_BG_STEALTH);
  }

  // Angular Brow Slant (Inward = Determined/Cool, Outward = Curious)
  if (browSlant > 0) {
    int slantH = min(browSlant, 18);
    if (isLeft) {
      // Slant inner top corner (right side of left eye)
      tft.fillTriangle(cx + w/2 - 20, cy - h/2 - 1, cx + w/2 + 2, cy - h/2 - 1, cx + w/2 + 2, cy - h/2 + slantH, COLOR_BG_STEALTH);
    } else {
      // Slant inner top corner (left side of right eye)
      tft.fillTriangle(cx - w/2 - 2, cy - h/2 - 1, cx - w/2 + 20, cy - h/2 - 1, cx - w/2 - 2, cy - h/2 + slantH, COLOR_BG_STEALTH);
    }
  } else if (browSlant < 0) {
    int slantH = min(-browSlant, 14);
    if (isLeft) {
      tft.fillTriangle(cx - w/2 - 2, cy - h/2 - 1, cx - w/2 + 16, cy - h/2 - 1, cx - w/2 - 2, cy - h/2 + slantH, COLOR_BG_STEALTH);
    } else {
      tft.fillTriangle(cx + w/2 - 16, cy - h/2 - 1, cx + w/2 + 2, cy - h/2 - 1, cx + w/2 + 2, cy - h/2 + slantH, COLOR_BG_STEALTH);
    }
  }

  // High-Tech Cyber Catchlight (horizontal energy slit, 12x4px)
  tft.fillRoundRect(cx + 4, cy - h/2 + 6, 14, 4, 2, COLOR_WHITE);
}

static void drawFaceFull(const LumoState& s) {
  tft.fillScreen(COLOR_BG_STEALTH);

  tft.fillRect(0, 0, 320, 32, COLOR_HEADER);
  tft.setFont(NULL);
  tft.setTextSize(2);
  tft.setTextColor(COLOR_WHITE);
  tft.setCursor(16, 8);
  tft.print("LUMO // SYSTEM");

  tft.setTextSize(1);
  tft.setTextColor(COLOR_MUTED);
  tft.setCursor(240, 12);
  tft.print("v1.3.0");

  tft.drawFastHLine(16, 30, 288, tft.color565(35, 45, 60));

  drawTimeBar(s, true);
}

static void drawFaceEyes(const LumoState& s) {
  int gx = animatorGetGazeX();
  int gy = animatorGetGazeY();

  AnimType anim = animatorGetAnim();

  // Audio beat groove bounce
  if (anim == ANIM_DANCE) {
    gy += (int)(sin(millis() / 110.0f) * 6.0f);
  }

  int lx = 100 + gx;
  int rx = 220 + gx;
  int cy = 104 + gy;

  // Clear animation area
  tft.fillRect(30, 34, 260, 166, COLOR_BG_STEALTH);

  // Notification Banner
  if (s.notif_active && (millis() - s.notif_start < 4500)) {
    tft.fillRoundRect(14, 36, 292, 48, 8, tft.color565(20, 25, 35));
    tft.drawRoundRect(14, 36, 292, 48, 8, COLOR_ACCENT);

    tft.setTextSize(1);
    tft.setTextColor(COLOR_ACCENT);
    tft.setCursor(24, 42);
    tft.printf("// ALERT: %s [%s]", s.notif_title, s.notif_app);

    tft.setTextSize(2);
    tft.setTextColor(COLOR_WHITE);
    tft.setCursor(24, 56);
    char cutBody[24];
    strncpy(cutBody, s.notif_body, sizeof(cutBody) - 1);
    cutBody[23] = '\0';
    tft.print(cutBody);

    cy += 16;
  }

  float el = animatorGetEyelidL();
  float er = animatorGetEyelidR();
  int   bl = animatorGetBrowL();
  int   br = animatorGetBrowR();

  uint16_t eyeCol = (s.eye_color != 0) ? s.eye_color : COLOR_ACCENT;
  if (anim == ANIM_ALERT) eyeCol = COLOR_RED_PULSE;

  bool isStandby = (anim == ANIM_STANDBY || s.schedule == SCHED_SLEEP);

  // Draw High-Tech Cyber Visor Eyes (56x48px, r=8)
  drawCyberEye(lx, cy, 56, 48, 8, el, eyeCol, true,  bl, isStandby);
  drawCyberEye(rx, cy, 56, 48, 8, er, eyeCol, false, br, isStandby);

  // Cyber Scanner Beam (ANIM_SCAN)
  if (anim == ANIM_SCAN) {
    int scanX = 50 + (int)((sin(millis() / 200.0f) + 1.0f) * 110.0f);
    tft.drawFastVLine(scanX, cy - 24, 48, COLOR_WHITE);
    tft.drawFastVLine(scanX + 1, cy - 24, 48, eyeCol);
  }

  // Audio Equalizer tick marks during beat
  if (anim == ANIM_DANCE) {
    tft.drawFastHLine(lx - 24, cy + 34, 48, eyeCol);
    tft.drawFastHLine(rx - 24, cy + 34, 48, eyeCol);
    int eqH = (int)(abs(sin(millis() / 150.0f)) * 10.0f);
    tft.fillRect(156, cy + 28 - eqH, 8, eqH * 2, eyeCol);
  }

  // Sleek Tech Mouth / Accents
  if (!isStandby && anim != ANIM_DANCE) {
    int mcx = 160 + gx, mcy = cy + 36;
    if (anim == ANIM_SMIRK) {
      // Confident smirk
      tft.drawLine(mcx - 12, mcy + 2, mcx + 14, mcy - 2, eyeCol);
      tft.drawLine(mcx - 12, mcy + 3, mcx + 14, mcy - 1, eyeCol);
    } else if (anim == ANIM_FOCUSED) {
      // Minimalist sensor line
      tft.drawFastHLine(mcx - 16, mcy, 32, eyeCol);
      tft.drawFastHLine(mcx - 8, mcy + 3, 16, COLOR_MUTED);
    } else if (s.mood == MOOD_SAD) {
      tft.drawFastHLine(mcx - 12, mcy + 4, 24, eyeCol);
    } else {
      // Clean level cyber smile
      tft.drawFastHLine(mcx - 14, mcy + 2, 28, eyeCol);
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
  tft.setTextColor(s.alarm_ringing ? COLOR_RED_PULSE : COLOR_ACCENT);
  tft.getTextBounds(aBuf, 0, 0, &x1, &y1, &w, &h);
  tft.setCursor((320 - w) / 2, 158);
  tft.print(aBuf);
}

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

  tft.fillRect(14, 42, 292, 18, COLOR_BG_BLACK);
  tft.setTextSize(2);
  tft.setTextColor(COLOR_WHITE);
  tft.setCursor(14, 42);
  tft.printf("CPU Temp: %.1f C", s.cpu_temp);
  drawProgressBar(14, 64, 292, 8, s.cpu_temp / 85.0f, (s.cpu_temp > 70.0f ? COLOR_RED_PULSE : COLOR_ACCENT), tft.color565(40, 40, 50));

  tft.fillRect(14, 82, 292, 18, COLOR_BG_BLACK);
  tft.setCursor(14, 82);
  tft.printf("CPU Load: %d%%", s.cpu_pct);
  drawProgressBar(14, 104, 292, 8, s.cpu_pct / 100.0f, COLOR_GREEN, tft.color565(40, 40, 50));

  tft.fillRect(14, 122, 292, 18, COLOR_BG_BLACK);
  tft.setCursor(14, 122);
  tft.printf("RAM:      %d%%", s.ram_pct);
  drawProgressBar(14, 144, 292, 8, s.ram_pct / 100.0f, COLOR_ACCENT, tft.color565(40, 40, 50));

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

    tft.setTextColor(COLOR_WHITE);
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
  int curSec = s.sp_progress_ms / 1000;
  int totSec = s.sp_duration_ms / 1000;
  tft.printf("%d:%02d / %d:%02d", curSec / 60, curSec % 60, totSec / 60, totSec % 60);

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
    tft.setCursor(12, y);
    tft.print("> ");

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
    tft.setCursor(40, 90);
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

  tft.setTextSize(3);
  tft.setTextColor(COLOR_WHITE);
  int16_t x1, y1; uint16_t w, h;
  const char* title = "ALERT: WAKE UP";
  tft.getTextBounds(title, 0, 0, &x1, &y1, &w, &h);
  tft.setCursor((320 - w) / 2, 45);
  tft.print(title);

  tft.setTextSize(5);
  char aBuf[16];
  snprintf(aBuf, sizeof(aBuf), "%02d:%02d", s.h, s.m);
  tft.getTextBounds(aBuf, 0, 0, &x1, &y1, &w, &h);
  tft.setCursor((320 - w) / 2, 100);
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
  tft.fillScreen(COLOR_BG_STEALTH);

  drawCyberEye(100, 100, 56, 48, 8, 1.0f, COLOR_ACCENT, true, 0, false);
  drawCyberEye(220, 100, 56, 48, 8, 1.0f, COLOR_ACCENT, false, 0, false);

  tft.setTextSize(2);
  tft.setTextColor(COLOR_WHITE);
  char msg[32];
  snprintf(msg, sizeof(msg), "Connecting to Pi%.*s", dotCount, "...");
  int16_t x1, y1; uint16_t w, h;
  tft.getTextBounds(msg, 0, 0, &x1, &y1, &w, &h);
  tft.setCursor((320 - w) / 2, 160);
  tft.print(msg);

  tft.setTextSize(1);
  tft.setTextColor(COLOR_MUTED);
  char ipBuf[40];
  snprintf(ipBuf, sizeof(ipBuf), "Host IP: %s", PI_HOSTNAME);
  tft.getTextBounds(ipBuf, 0, 0, &x1, &y1, &w, &h);
  tft.setCursor((320 - w) / 2, 195);
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
