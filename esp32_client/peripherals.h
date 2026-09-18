#pragma once
#include "config.h"
#include <Adafruit_NeoPixel.h>

extern Adafruit_NeoPixel pixels;

void     initNeoPixels();
void     applyNeoPixels(NeoMode mode, uint8_t brightness, uint16_t hue);
void     neoAlarmFlash();
void     neoClear();

Button   readButton();
void     hapticPulse(uint16_t ms);
void     hapticOff();
void     hapticUpdate();
