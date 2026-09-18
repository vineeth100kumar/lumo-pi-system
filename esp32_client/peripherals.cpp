#include <Arduino.h>
#include "peripherals.h"
#include <math.h>

Adafruit_NeoPixel pixels(NUMPIXELS, NEOPIXEL_PIN, NEO_GRB + NEO_KHZ800);

static unsigned long hapticEndTime = 0;
static bool hapticActive = false;

void hapticPulse(uint16_t ms) {
  ledcWrite(BUZZER_PIN, 5);
  hapticEndTime = millis() + ms;
  hapticActive = true;
}

void hapticOff() {
  ledcWrite(BUZZER_PIN, 255);
  hapticActive = false;
}

void hapticUpdate() {
  if (hapticActive && millis() >= hapticEndTime) {
    hapticOff();
  }
}

void initNeoPixels() {
  pixels.begin();
  pixels.setBrightness(40);
  pixels.clear();
  pixels.show();
}

void applyNeoPixels(NeoMode mode, uint8_t brightness, uint16_t hue) {
  pixels.setBrightness(brightness);

  if (mode == NEO_OFF) {
    pixels.clear();
    pixels.show();
    return;
  }

  if (mode == NEO_WARM) {
    for (int i = 0; i < NUMPIXELS; i++) {
      pixels.setPixelColor(i, pixels.Color(255, 140, 40));
    }
  } else if (mode == NEO_COLOR) {
    uint16_t hue16 = (uint32_t)hue * 65535 / 360;
    uint32_t c = pixels.gamma32(pixels.ColorHSV(hue16, 255, 255));
    for (int i = 0; i < NUMPIXELS; i++) {
      pixels.setPixelColor(i, c);
    }
  } else if (mode == NEO_BREATHE) {
    static int phase = 0;
    phase = (phase + 4) % 360;
    float rad = phase * 0.0174533f;
    int b = (int)((sin(rad) + 1.0f) * 0.5f * (brightness - 10)) + 10;
    pixels.setBrightness(constrain(b, 5, brightness));
    uint16_t hue16 = (uint32_t)hue * 65535 / 360;
    uint32_t c = pixels.gamma32(pixels.ColorHSV(hue16, 255, 255));
    for (int i = 0; i < NUMPIXELS; i++) {
      pixels.setPixelColor(i, c);
    }
  }

  pixels.show();
}

void neoAlarmFlash() {
  static unsigned long lastFlash = 0;
  static bool state = false;
  if (millis() - lastFlash > 250) {
    lastFlash = millis();
    state = !state;
    pixels.setBrightness(80);
    if (state) {
      for (int i = 0; i < NUMPIXELS; i++) pixels.setPixelColor(i, pixels.Color(255, 0, 0));
    } else {
      pixels.clear();
    }
    pixels.show();
  }
}

void neoClear() {
  pixels.clear();
  pixels.show();
}

Button readButton() {
  static Button lastStable = BTN_NONE;
  static unsigned long pressStart = 0;
  static unsigned long lastRepeat = 0;

  const unsigned long HOLD_START_MS  = 350;
  const unsigned long HOLD_REPEAT_MS = 120;

  int raw = analogRead(BUTTON_PIN);
  float v = (raw / 4095.0f) * 3.3f;

  Button cur = BTN_NONE;
  if (fabs(v - V_OK) <= V_TOL)        cur = BTN_OK;
  else if (fabs(v - V_UP) <= V_TOL)   cur = BTN_UP;
  else if (fabs(v - V_DOWN) <= V_TOL) cur = BTN_DOWN;
  else if (fabs(v - V_LEFT) <= V_TOL) cur = BTN_LEFT;
  else if (fabs(v - V_RIGHT) <= V_TOL)cur = BTN_RIGHT;

  if (cur != BTN_NONE && lastStable == BTN_NONE) {
    lastStable = cur;
    pressStart = millis();
    lastRepeat = millis();
    return cur;
  }

  if (cur == BTN_NONE && lastStable != BTN_NONE) {
    lastStable = BTN_NONE;
    return BTN_NONE;
  }

  if ((cur == BTN_UP || cur == BTN_DOWN) && cur == lastStable) {
    unsigned long now = millis();
    if (now - pressStart > HOLD_START_MS && now - lastRepeat > HOLD_REPEAT_MS) {
      lastRepeat = now;
      return cur;
    }
  }

  return BTN_NONE;
}
