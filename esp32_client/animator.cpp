#include <Arduino.h>
#include "animator.h"
#include <math.h>

static LumoMood     currentMood     = MOOD_NORMAL;
static CharSchedule currentSchedule = SCHED_AWAKE;
static AnimType     currentAnim     = ANIM_NORMAL;

static bool needsRedraw = true;

// Smooth gaze positions (lerped at 60 FPS)
static float targetGazeX = 0.0f;
static float targetGazeY = 0.0f;
static float currGazeX   = 0.0f;
static float currGazeY   = 0.0f;

// Eyelids (0.0 = fully closed, 1.0 = fully open)
static float targetEyelidL = 1.0f;
static float targetEyelidR = 1.0f;
static float currEyelidL   = 1.0f;
static float currEyelidR   = 1.0f;

// Animation timer
static unsigned long animStartTime = 0;
static unsigned long animDuration  = 0;

// Natural blink timer
static unsigned long lastBlinkStart = 0;
static unsigned long blinkInterval  = 4000;
static bool          isBlinking     = false;

static unsigned long getBlinkGap() {
  if (currentSchedule == SCHED_SLEEP) return 999999;
  if (currentSchedule == SCHED_DROWSY) return random(6000, 10000);

  switch (currentMood) {
    case MOOD_HAPPY:   return random(3000, 5000);
    case MOOD_BORED:   return random(7000, 11000);
    case MOOD_SAD:     return random(9000, 14000);
    case MOOD_EXCITED: return random(2000, 3500);
    default:           return random(4000, 7000);
  }
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
  currentAnim    = anim;
  targetGazeX    = (float)gx;
  targetGazeY    = (float)gy;
  animStartTime  = millis();
  animDuration   = durationMs;
  needsRedraw    = true;

  if (anim == ANIM_WINK_L) {
    targetEyelidL = 0.0f;
    targetEyelidR = 1.0f;
  } else if (anim == ANIM_WINK_R) {
    targetEyelidL = 1.0f;
    targetEyelidR = 0.0f;
  } else if (anim == ANIM_SLEEPY) {
    targetEyelidL = 0.35f;
    targetEyelidR = 0.35f;
  } else {
    targetEyelidL = 1.0f;
    targetEyelidR = 1.0f;
  }
}

void animatorTick() {
  unsigned long now = millis();

  // 1. One-shot animation expiration
  if (animDuration > 0 && (now - animStartTime >= animDuration)) {
    animDuration  = 0;
    currentAnim   = ANIM_NORMAL;
    targetGazeX   = 0.0f;
    targetGazeY   = 0.0f;
    targetEyelidL = 1.0f;
    targetEyelidR = 1.0f;
    needsRedraw   = true;
  }

  // 2. Natural local blinks (when not playing an overriding animation)
  if (currentSchedule == SCHED_SLEEP) {
    targetEyelidL = 0.0f;
    targetEyelidR = 0.0f;
  } else if (currentAnim == ANIM_NORMAL || currentAnim == ANIM_LOOK) {
    if (!isBlinking) {
      if (now - lastBlinkStart >= blinkInterval) {
        isBlinking     = true;
        lastBlinkStart = now;
        targetEyelidL  = 0.0f;
        targetEyelidR  = 0.0f;
      }
    } else {
      if (now - lastBlinkStart >= 120) {
        isBlinking     = false;
        lastBlinkStart = now;
        blinkInterval  = getBlinkGap();
        targetEyelidL  = 1.0f;
        targetEyelidR  = 1.0f;
      }
    }
  }

  // 3. Smooth 60 FPS interpolation (Lerp)
  float oldGx = currGazeX, oldGy = currGazeY;
  float oldEl = currEyelidL, oldEr = currEyelidR;

  currGazeX += (targetGazeX - currGazeX) * 0.30f;
  currGazeY += (targetGazeY - currGazeY) * 0.30f;
  currEyelidL += (targetEyelidL - currEyelidL) * 0.38f;
  currEyelidR += (targetEyelidR - currEyelidR) * 0.38f;

  if (fabs(currGazeX - targetGazeX) < 0.2f) currGazeX = targetGazeX;
  if (fabs(currGazeY - targetGazeY) < 0.2f) currGazeY = targetGazeY;
  if (fabs(currEyelidL - targetEyelidL) < 0.05f) currEyelidL = targetEyelidL;
  if (fabs(currEyelidR - targetEyelidR) < 0.05f) currEyelidR = targetEyelidR;

  // If dynamic visual parameters shifted, trigger repaint
  if (fabs(currGazeX - oldGx) > 0.4f || fabs(currGazeY - oldGy) > 0.4f ||
      fabs(currEyelidL - oldEl) > 0.05f || fabs(currEyelidR - oldEr) > 0.05f ||
      currentAnim == ANIM_DANCE) {
    needsRedraw = true;
  }
}

bool animatorNeedsRedraw() { return needsRedraw; }
void animatorClearRedraw() { needsRedraw = false; }

int   animatorGetGazeX()   { return (int)currGazeX; }
int   animatorGetGazeY()   { return (int)currGazeY; }
float animatorGetEyelidL() { return currEyelidL; }
float animatorGetEyelidR() { return currEyelidR; }
AnimType animatorGetAnim() { return currentAnim; }

bool animatorEyesOpen() {
  return (currEyelidL > 0.2f || currEyelidR > 0.2f);
}

bool animatorSmileVisible() {
  return (currentSchedule == SCHED_AWAKE);
}

bool animatorYawning() {
  return (currentAnim == ANIM_SLEEPY);
}
