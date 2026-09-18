#pragma once
#include "config.h"
#include <Adafruit_GFX.h>
#include <Adafruit_ILI9341.h>

extern Adafruit_ILI9341 tft;
extern uint8_t artBuf[20004];
extern bool newArtReady;

void displayInit();
void displayDrawScreen(ScreenMode mode, const LumoState& s, bool forceFullRedraw);
void drawTimeBar(const LumoState& s, bool force);
void drawProgressBar(int x, int y, int w, int h, float pct, uint16_t fillColor, uint16_t bgColor);
void onNewArt(const uint8_t* data, size_t len);
