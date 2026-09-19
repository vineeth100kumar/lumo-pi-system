#include <Arduino.h>
#include "display.h"
#include "animator.h"
#include <math.h>

Adafruit_ILI9341 tft = Adafruit_ILI9341(TFT_CS, TFT_DC);

uint8_t artBuf[20004];
bool newArtReady = false;

static const uint16_t COLOR_BG_BLACK  = 0x0000;
static const uint16_t COLOR_BG_NAVY   = 0x08A5; // tft.color565(10, 20, 45)
static const uint16_t COLOR_HEADER    = 0x08A5;
static const uint16_t COLOR_TIME_BAR  = 0x0842; // tft.color565(8, 10, 20)
static const uint16_t COLOR_SMILE     = 0x077F; // Cyan smile
static const uint16_t COLOR_WHITE     = 0xFFFF;
static const uint16_t COLOR_MUTED     = 0x7BEF;
static const uint16_t COLOR_ACCENT    = 0x2BDF;
static const uint16_t COLOR_GREEN     = 0x1DB4;
static const uint16_t COLOR_RED_PULSE = 0xD800;
static const uint16_t COLOR_BLUSH     = 0xFBAF; // Soft pink blush
static const uint16_t COLOR_HOT_PINK  = 0xF9B3; // Heart eyes

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

  tft.fillRect(0, 202, 320, 38, COLOR_TIME_BAR);

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
  tft.setCursor(195, 212);
  tft.print(dateBuf);
}

static void drawVectorHeart(int cx, int cy, int size, uint16_t color) {
  int r = size / 2;
  tft.fillCircle(cx - r/2, cy - r/4, r/2, color);
  tft.fillCircle(cx + r/2, cy - r/4, r/2, color);
  tft.fillTriangle(cx - r, cy, cx + r, cy, cx, cy + size, color);
}

static void drawSingleEye(int cx, int cy, int w, int h, int r, float eyelid, uint16_t color, bool isWinking, bool isHeart, bool isHappy) {
  if (isHeart) {
    drawVectorHeart(cx, cy - 4, 34, COLOR_HOT_PINK);
    return;
  }

  if (isHappy) {
    // Upward crescent arch (^ ^)
    tft.fillRoundRect(cx - 24, cy - 10, 48, 26, 12, color);
    tft.fillRoundRect(cx - 27, cy - 2, 54, 28, 12, COLOR_BG_NAVY);
    return;
  }

  if (isWinking || eyelid <= 0.15f) {
    // Cute curved wink line
    tft.fillRoundRect(cx - 22, cy + 4, 44, 6, 3, color);
    return;
  }

  // Large smooth stadium capsule eye
  tft.fillRoundRect(cx - w/2, cy - h/2, w, h, r, color);

  // Glassy Specular Catchlight (white rounded reflection glint)
  tft.fillRoundRect(cx + 7, cy - h/2 + 8, 10, 10, 4, COLOR_WHITE);
  tft.fillCircle(cx + 4, cy - h/2 + 24, 3, COLOR_WHITE);

  // Eyelid masking from top if partially closed
  if (eyelid < 0.95f) {
    int clipH = (int)(h * (1.0f - eyelid));
    tft.fillRect(cx - w/2 - 2, cy - h/2 - 2, w + 4, clipH + 2, COLOR_BG_NAVY);
  }
}

static void drawFaceFull(const LumoState& s) {
  tft.fillScreen(COLOR_BG_NAVY);

  tft.fillRect(0, 0, 320, 32, COLOR_HEADER);
  tft.setFont(NULL);
  tft.setTextSize(2);
  tft.setTextColor(COLOR_WHITE);
  int16_t x1, y1; uint16_t w, h;
  tft.getTextBounds("LUMO", 0, 0, &x1, &y1, &w, &h);
  tft.setCursor((320 - w) / 2, 8);
  tft.print("LUMO");
  tft.drawFastHLine(60, 30, 200, tft.color565(30, 60, 110));

  drawTimeBar(s, true);
}

static void drawFaceEyes(const LumoState& s) {
  int gx = animatorGetGazeX();
  int gy = animatorGetGazeY();

  // Music dancing bounce
  if (animatorGetAnim() == ANIM_DANCE) {
    gy += (int)(sin(millis() / 120.0f) * 7.0f);
  }

  int lx = 105 + gx;
  int rx = 215 + gx;
  int cy = 102 + gy;

  // Clear animation dirty-rectangle
  tft.fillRect(40, 36, 240, 164, COLOR_BG_NAVY);

  // Check notification banner
  if (s.notif_active && (millis() - s.notif_start < 4500)) {
    tft.fillRoundRect(16, 38, 288, 50, 10, tft.color565(25, 45, 80));
    tft.drawRoundRect(16, 38, 288, 50, 10, COLOR_ACCENT);

    tft.setTextSize(1);
    tft.setTextColor(COLOR_ACCENT);
    tft.setCursor(26, 44);
    tft.printf("[%s] %s", s.notif_app, s.notif_title);

    tft.setTextSize(2);
    tft.setTextColor(COLOR_WHITE);
    tft.setCursor(26, 58);
    char cutBody[24];
    strncpy(cutBody, s.notif_body, sizeof(cutBody) - 1);
    cutBody[23] = '\0';
    tft.print(cutBody);

    cy += 14; // Push eyes down slightly when banner is showing
  }

  AnimType anim = animatorGetAnim();
  float el = animatorGetEyelidL();
  float er = animatorGetEyelidR();

  uint16_t eyeCol = (s.eye_color != 0) ? s.eye_color : COLOR_SMILE;

  bool isHeart = (anim == ANIM_HEART);
  bool isHappy = (anim == ANIM_HAPPY);

  // Draw Left & Right Eyes (52x68px, r=16)
  drawSingleEye(lx, cy, 52, 68, 16, el, eyeCol, (anim == ANIM_WINK_L), isHeart, isHappy);
  drawSingleEye(rx, cy, 52, 68, 16, er, eyeCol, (anim == ANIM_WINK_R), isHeart, isHappy);

  // Cute soft blush marks below each eye
  tft.fillRoundRect(lx - 14, cy + 44, 28, 7, 3, COLOR_BLUSH);
  tft.fillRoundRect(rx - 14, cy + 44, 28, 7, 3, COLOR_BLUSH);

  // Music Notes floating when dancing
  if (anim == ANIM_DANCE) {
    tft.setTextSize(2);
    tft.setTextColor(COLOR_WHITE);
    tft.setCursor(lx - 28, cy - 35);
    tft.print("♫");
    tft.setCursor(rx + 18, cy - 40);
    tft.print("♪");
  }

  // Expressive Mouth
  if (animatorYawning()) {
    tft.fillRoundRect(150, cy + 34, 20, 26, 10, eyeCol);
  } else if (animatorSmileVisible() && !isHeart && !isHappy) {
    int mcx = 160 + gx, mcy = cy + 42, r = 20;
    if (s.mood == MOOD_SAD) {
      for (int x = -r; x <= r; x++) {
        int dy = (int)(sqrt(r * r - x * x) / 4.2f);
        tft.drawPixel(mcx + x, mcy + 6 - dy, eyeCol);
      }
    } else if (s.mood == MOOD_BORED) {
      tft.drawFastHLine(mcx - 14, mcy + 2, 28, eyeCol);
    } else {
      for (int x = -r; x <= r; x++) {
        int dy = (int)(sqrt(r * r - x * x) / 4.2f);
        tft.drawPixel(mcx + x, mcy + dy, eyeCol);
        tft.drawPixel(mcx + x, mcy + dy + 1, eyeCol);
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
    tft.print("o ");

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
  const char* title = "WAKE UP!";
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
  tft.fillScreen(COLOR_BG_NAVY);

  drawSingleEye(105, 100, 48, 62, 14, 1.0f, COLOR_ACCENT, false, false, false);
  drawSingleEye(215, 100, 48, 62, 14, 1.0f, COLOR_ACCENT, false, false, false);

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
  snprintf(ipBuf, sizeof(ipBuf), "Server IP: %s", PI_HOSTNAME);
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
