#include <Arduino.h>
#include "animator.h"
#include <math.h>

static LumoMood     currentMood     = MOOD_NORMAL;
static CharSchedule currentSchedule = SCHED_AWAKE;
static AnimType     currentAnim     = ANIM_NORMAL;

static bool needsRedraw = true;

// Gaze offset
static float targetGazeX = 0.0f;
static float targetGazeY = 0.0f;
static float currGazeX   = 0.0f;
static float currGazeY   = 0.0f;

// Eyelids (0.0 = closed, 1.0 = open)
static float targetEyelidL = 1.0f;
static float targetEyelidR = 1.0f;
static float currEyelidL   = 1.0f;
static float currEyelidR   = 1.0f;

// Brow slant angles (positive = inward determined, negative = outward curious)
static float targetBrowL = 0.0f;
static float targetBrowR = 0.0f;
static float currBrowL   = 0.0f;
static float currBrowR   = 0.0f;

// Timers
static unsigned long animStartTime = 0;
static unsigned long animDuration  = 0;
static unsigned long lastBlinkStart = 0;
static unsigned long blinkInterval  = 4500;
static bool          isBlinking     = false;

static unsigned long getBlinkGap() {
  if (currentSchedule == SCHED_SLEEP) return 999999;
  return random(3500, 6500);
}

void animatorInit() {
  randomSeed(analogRead(0) ^ millis());
  needsRedraw    = true;
  lastBlinkStart = millis();
  blinkInterval  = getBlinkGap();
  currEyelidL    = 1.0f;
  currEyelidR    = 1.0f;
  currGazeX      = 0.0f;
  currGazeY      = 0.0f;
  currBrowL      = 0.0f;
  currBrowR      = 0.0f;
}

void animatorSetMood(LumoMood mood, CharSchedule sched) {
  if (currentMood != mood || currentSchedule != sched) {
    currentMood     = mood;
    currentSchedule = sched;
    blinkInterval   = getBlinkGap();
    needsRedraw     = true;
  }
}

void animatorSetAnim(AnimType anim, int8_t gx, int8_t gy, unsigned long durationMs) {
  currentAnim   = anim;
  targetGazeX   = (float)gx;
  targetGazeY   = (float)gy;
  animStartTime = millis();
  animDuration  = durationMs;
  needsRedraw   = true;

  if (anim == ANIM_FOCUSED) {
    targetBrowL   = 12.0f; // Determined sharp brow
    targetBrowR   = 12.0f;
    targetEyelidL = 0.85f;
    targetEyelidR = 0.85f;
  } else if (anim == ANIM_SMIRK) {
    targetBrowL   = 14.0f;
    targetBrowR   = -6.0f; // Cocked brow
    targetEyelidL = 0.90f;
    targetEyelidR = 1.0f;
  } else if (anim == ANIM_CURIOUS) {
    targetBrowL   = -10.0f;
    targetBrowR   = 8.0f;
    targetEyelidL = 1.0f;
    targetEyelidR = 0.9f;
  } else if (anim == ANIM_ALERT) {
    targetBrowL   = 6.0f;
    targetBrowR   = 6.0f;
    targetEyelidL = 1.0f;
    targetEyelidR = 1.0f;
  } else if (anim == ANIM_STANDBY) {
    targetBrowL   = 0.0f;
    targetBrowR   = 0.0f;
    targetEyelidL = 0.0f;
    targetEyelidR = 0.0f;
  } else {
    targetBrowL   = 0.0f;
    targetBrowR   = 0.0f;
    targetEyelidL = 1.0f;
    targetEyelidR = 1.0f;
  }
}

void animatorTick() {
  unsigned long now = millis();

  // 1. One-shot timeout
  if (animDuration > 0 && (now - animStartTime >= animDuration)) {
    animDuration  = 0;
    currentAnim   = ANIM_NORMAL;
    targetGazeX   = 0.0f;
    targetGazeY   = 0.0f;
    targetBrowL   = 0.0f;
    targetBrowR   = 0.0f;
    targetEyelidL = 1.0f;
    targetEyelidR = 1.0f;
    needsRedraw   = true;
  }

  // 2. Snappy shutter blinks (85ms camera-shutter feel)
  if (currentSchedule == SCHED_SLEEP) {
    targetEyelidL = 0.0f;
    targetEyelidR = 0.0f;
  } else if (currentAnim == ANIM_NORMAL || currentAnim == ANIM_LOOK || currentAnim == ANIM_FOCUSED) {
    if (!isBlinking) {
      if (now - lastBlinkStart >= blinkInterval) {
        isBlinking     = true;
        lastBlinkStart = now;
        targetEyelidL  = 0.0f;
        targetEyelidR  = 0.0f;
      }
    } else {
      if (now - lastBlinkStart >= 85) {
        isBlinking     = false;
        lastBlinkStart = now;
        blinkInterval  = getBlinkGap();
        targetEyelidL  = (currentAnim == ANIM_FOCUSED) ? 0.85f : 1.0f;
        targetEyelidR  = (currentAnim == ANIM_FOCUSED) ? 0.85f : 1.0f;
      }
    }
  }

  // 3. Smooth 60 FPS Lerp
  float oldGx = currGazeX, oldGy = currGazeY;
  float oldEl = currEyelidL, oldEr = currEyelidR;
  float oldBl = currBrowL,   oldBr = currBrowR;

  currGazeX   += (targetGazeX   - currGazeX)   * 0.35f;
  currGazeY   += (targetGazeY   - currGazeY)   * 0.35f;
  currEyelidL += (targetEyelidL - currEyelidL) * 0.45f;
  currEyelidR += (targetEyelidR - currEyelidR) * 0.45f;
  currBrowL   += (targetBrowL   - currBrowL)   * 0.35f;
  currBrowR   += (targetBrowR   - currBrowR)   * 0.35f;

  if (fabs(currGazeX - targetGazeX) < 0.2f) currGazeX = targetGazeX;
  if (fabs(currGazeY - targetGazeY) < 0.2f) currGazeY = targetGazeY;
  if (fabs(currEyelidL - targetEyelidL) < 0.04f) currEyelidL = targetEyelidL;
  if (fabs(currEyelidR - targetEyelidR) < 0.04f) currEyelidR = targetEyelidR;
  if (fabs(currBrowL - targetBrowL) < 0.2f) currBrowL = targetBrowL;
  if (fabs(currBrowR - targetBrowR) < 0.2f) currBrowR = targetBrowR;

  if (fabs(currGazeX - oldGx) > 0.3f || fabs(currGazeY - oldGy) > 0.3f ||
      fabs(currEyelidL - oldEl) > 0.04f || fabs(currEyelidR - oldEr) > 0.04f ||
      fabs(currBrowL - oldBl) > 0.3f   || fabs(currBrowR - oldBr) > 0.3f ||
      currentAnim == ANIM_DANCE || currentAnim == ANIM_SCAN) {
    needsRedraw = true;
  }
}

bool animatorNeedsRedraw() { return needsRedraw; }
void animatorClearRedraw() { needsRedraw = false; }

int      animatorGetGazeX()   { return (int)currGazeX; }
int      animatorGetGazeY()   { return (int)currGazeY; }
float    animatorGetEyelidL() { return currEyelidL; }
float    animatorGetEyelidR() { return currEyelidR; }
int      animatorGetBrowL()   { return (int)currBrowL; }
int      animatorGetBrowR()   { return (int)currBrowR; }
AnimType animatorGetAnim()    { return currentAnim; }

bool animatorEyesOpen() {
  return (currEyelidL > 0.15f || currEyelidR > 0.15f);
}

bool animatorSmileVisible() {
  return (currentSchedule == SCHED_AWAKE);
}
