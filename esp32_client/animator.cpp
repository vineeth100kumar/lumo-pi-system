#include <Arduino.h>
#include "animator.h"
#include <math.h>

static LumoMood     currentMood     = MOOD_NORMAL;
static CharSchedule currentSchedule = SCHED_AWAKE;
static AnimType     currentAnim     = ANIM_NORMAL;
static MouthShape   currentMouth    = MOUTH_SMILE;

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

// Expressive Dynamic Eye Dimensions (Anki Vector / Cozmo style)
static float targetEyeWL = 56.0f;
static float targetEyeWR = 56.0f;
static float currEyeWL   = 56.0f;
static float currEyeWR   = 56.0f;

static float targetEyeHL = 48.0f;
static float targetEyeHR = 48.0f;
static float currEyeHL   = 48.0f;
static float currEyeHR   = 48.0f;

static float targetEyeR  = 8.0f;
static float currEyeR    = 8.0f;

// Animation & Blink Timers
static unsigned long animStartTime    = 0;
static unsigned long animDuration     = 0;
static unsigned long lastBlinkStart   = 0;
static unsigned long blinkInterval    = 4500;
static bool          isBlinking       = false;
static unsigned long blinkStaggerRMs  = 0;
static bool          isWink           = false;

// Idle Alive Micro-Saccades
static unsigned long lastSaccadeTime  = 0;
static unsigned long saccadeInterval  = 3200;

static unsigned long getBlinkGap() {
  if (currentSchedule == SCHED_SLEEP) return 999999;
  if (currentMood == MOOD_BORED) return random(5000, 8500);
  if (currentMood == MOOD_HAPPY) return random(3000, 5500);
  return random(3500, 6500);
}

static void applyMoodAndAnimTargets() {
  if (currentSchedule == SCHED_SLEEP) {
    targetEyeWL   = 54.0f; targetEyeWR = 54.0f;
    targetEyeHL   = 12.0f; targetEyeHR = 12.0f;
    targetEyeR    = 3.0f;
    targetBrowL   = 0.0f;  targetBrowR = 0.0f;
    targetEyelidL = 0.0f;  targetEyelidR = 0.0f;
    currentMouth  = MOUTH_NEUTRAL;
    return;
  }

  // Set expressive geometry according to AnimType or Mood
  if (currentAnim == ANIM_FOCUSED) {
    // Narrow & determined squint (Vector focused probe)
    targetEyeWL   = 52.0f; targetEyeWR = 52.0f;
    targetEyeHL   = 34.0f; targetEyeHR = 34.0f;
    targetEyeR    = 6.0f;
    targetBrowL   = 12.0f; targetBrowR = 12.0f;
    targetEyelidL = 0.85f; targetEyelidR = 0.85f;
    currentMouth  = MOUTH_FOCUSED;
  } else if (currentAnim == ANIM_SMIRK) {
    // Asymmetric sly cocked expression
    targetEyeWL   = 54.0f; targetEyeWR = 56.0f;
    targetEyeHL   = 46.0f; targetEyeHR = 40.0f;
    targetEyeR    = 8.0f;
    targetBrowL   = 14.0f; targetBrowR = -6.0f;
    targetEyelidL = 0.90f; targetEyelidR = 1.0f;
    currentMouth  = MOUTH_SMIRK;
  } else if (currentAnim == ANIM_CURIOUS) {
    // Asymmetric curious tilt (one eye taller & inquisitive)
    targetEyeWL   = 58.0f; targetEyeWR = 52.0f;
    targetEyeHL   = 52.0f; targetEyeHR = 42.0f;
    targetEyeR    = 10.0f;
    targetBrowL   = -10.0f; targetBrowR = 8.0f;
    targetEyelidL = 1.0f;   targetEyelidR = 0.9f;
    currentMouth  = MOUTH_SMILE;
  } else if (currentAnim == ANIM_ALERT) {
    // Wide & tall surprised/alert round eyes
    targetEyeWL   = 60.0f; targetEyeWR = 60.0f;
    targetEyeHL   = 54.0f; targetEyeHR = 54.0f;
    targetEyeR    = 14.0f;
    targetBrowL   = 6.0f;  targetBrowR = 6.0f;
    targetEyelidL = 1.0f;  targetEyelidR = 1.0f;
    currentMouth  = MOUTH_SURPRISED;
  } else if (currentAnim == ANIM_STANDBY) {
    targetEyeWL   = 56.0f; targetEyeWR = 56.0f;
    targetEyeHL   = 8.0f;  targetEyeHR = 8.0f;
    targetEyeR    = 3.0f;
    targetBrowL   = 0.0f;  targetBrowR = 0.0f;
    targetEyelidL = 0.0f;  targetEyelidR = 0.0f;
    currentMouth  = MOUTH_NEUTRAL;
  } else {
    // Base expressions driven by LumoMood
    if (currentMood == MOOD_HAPPY || currentMood == MOOD_EXCITED) {
      // Squashed, wide friendly eyes with rounded corners (Cozmo joy)
      targetEyeWL   = 62.0f; targetEyeWR = 62.0f;
      targetEyeHL   = 36.0f; targetEyeHR = 36.0f;
      targetEyeR    = 10.0f;
      targetBrowL   = 4.0f;  targetBrowR = 4.0f;
      targetEyelidL = 0.95f; targetEyelidR = 0.95f;
      currentMouth  = MOUTH_SMILE;
    } else if (currentMood == MOOD_BORED) {
      // Flat low-profile sleepy visor
      targetEyeWL   = 58.0f; targetEyeWR = 58.0f;
      targetEyeHL   = 28.0f; targetEyeHR = 28.0f;
      targetEyeR    = 4.0f;
      targetBrowL   = -2.0f; targetBrowR = -2.0f;
      targetEyelidL = 0.75f; targetEyelidR = 0.75f;
      currentMouth  = MOUTH_NEUTRAL;
    } else if (currentMood == MOOD_SAD) {
      // Slightly narrower drooping eye shape
      targetEyeWL   = 50.0f; targetEyeWR = 50.0f;
      targetEyeHL   = 38.0f; targetEyeHR = 38.0f;
      targetEyeR    = 7.0f;
      targetBrowL   = -8.0f; targetBrowR = -8.0f;
      targetEyelidL = 0.85f; targetEyelidR = 0.85f;
      currentMouth  = MOUTH_SAD;
    } else {
      // MOOD_NORMAL: Standard clean cyber companion
      targetEyeWL   = 56.0f; targetEyeWR = 56.0f;
      targetEyeHL   = 48.0f; targetEyeHR = 48.0f;
      targetEyeR    = 8.0f;
      targetBrowL   = 0.0f;  targetBrowR = 0.0f;
      targetEyelidL = 1.0f;  targetEyelidR = 1.0f;
      currentMouth  = MOUTH_SMILE;
    }
  }
}

void animatorInit() {
  randomSeed(analogRead(0) ^ millis());
  needsRedraw     = true;
  lastBlinkStart  = millis();
  blinkInterval   = getBlinkGap();
  lastSaccadeTime = millis();
  saccadeInterval = random(2500, 4800);

  currEyelidL = 1.0f; currEyelidR = 1.0f;
  currGazeX   = 0.0f; currGazeY   = 0.0f;
  currBrowL   = 0.0f; currBrowR   = 0.0f;
  currEyeWL   = 56.0f; currEyeWR  = 56.0f;
  currEyeHL   = 48.0f; currEyeHR  = 48.0f;
  currEyeR    = 8.0f;

  applyMoodAndAnimTargets();
}

void animatorSetMood(LumoMood mood, CharSchedule sched) {
  if (currentMood != mood || currentSchedule != sched) {
    currentMood     = mood;
    currentSchedule = sched;
    blinkInterval   = getBlinkGap();
    applyMoodAndAnimTargets();
    needsRedraw     = true;
  }
}

void animatorSetAnim(AnimType anim, int8_t gx, int8_t gy, unsigned long durationMs) {
  currentAnim   = anim;
  targetGazeX   = (float)gx;
  targetGazeY   = (float)gy;
  animStartTime = millis();
  animDuration  = durationMs;

  applyMoodAndAnimTargets();
  needsRedraw = true;
}

void animatorTick() {
  unsigned long now = millis();

  // 1. One-shot timeout
  if (animDuration > 0 && (now - animStartTime >= animDuration)) {
    animDuration = 0;
    currentAnim  = ANIM_NORMAL;
    targetGazeX  = 0.0f;
    targetGazeY  = 0.0f;
    applyMoodAndAnimTargets();
    needsRedraw  = true;
  }

  // 2. Idle "Alive" Micro-Saccades (Autonomous Gaze Wander)
  if (currentSchedule != SCHED_SLEEP && currentAnim == ANIM_NORMAL && animDuration == 0) {
    if (now - lastSaccadeTime >= saccadeInterval) {
      lastSaccadeTime = now;
      saccadeInterval = random(2400, 5200);

      // 25% chance return to dead-center, 75% subtle spontaneous gaze shift
      if (random(0, 100) < 25) {
        targetGazeX = 0.0f;
        targetGazeY = 0.0f;
      } else {
        targetGazeX = (float)random(-4, 5); // ±4 px horizontal dart
        targetGazeY = (float)random(-2, 3); // ±2 px vertical micro-drift
      }
      needsRedraw = true;
    }
  }

  // 3. Asymmetric & Staggered Shutter Blinking
  if (currentSchedule == SCHED_SLEEP) {
    targetEyelidL = 0.0f;
    targetEyelidR = 0.0f;
  } else if (currentAnim == ANIM_NORMAL || currentAnim == ANIM_LOOK || currentAnim == ANIM_FOCUSED) {
    if (!isBlinking) {
      if (now - lastBlinkStart >= blinkInterval) {
        isBlinking        = true;
        lastBlinkStart    = now;
        blinkStaggerRMs   = random(0, 32); // 0-32ms organic lag between L and R
        isWink            = (random(0, 100) < 6); // Rare 6% playful single-eye wink

        targetEyelidL = 0.0f;
        targetEyelidR = isWink ? 0.85f : 0.0f;
      }
    } else {
      unsigned long elapsed = now - lastBlinkStart;
      if (elapsed >= 95 + blinkStaggerRMs) {
        isBlinking     = false;
        lastBlinkStart = now;
        blinkInterval  = getBlinkGap();

        float openLevelL = (currentAnim == ANIM_FOCUSED) ? 0.85f : (currentMood == MOOD_BORED ? 0.75f : 1.0f);
        float openLevelR = openLevelL;
        targetEyelidL = openLevelL;
        targetEyelidR = openLevelR;
      }
    }
  }

  // 4. Smooth 60 FPS Organic Lerp
  float oldGx = currGazeX,   oldGy = currGazeY;
  float oldEl = currEyelidL, oldEr = currEyelidR;
  float oldBl = currBrowL,   oldBr = currBrowR;
  float oldWL = currEyeWL,   oldWR = currEyeWR;
  float oldHL = currEyeHL,   oldHR = currEyeHR;

  // Snappy ocular saccades (0.38f) + smooth geometry transitions (0.30f)
  currGazeX   += (targetGazeX   - currGazeX)   * 0.38f;
  currGazeY   += (targetGazeY   - currGazeY)   * 0.38f;
  currEyelidL += (targetEyelidL - currEyelidL) * 0.45f;
  currEyelidR += (targetEyelidR - currEyelidR) * 0.45f;
  currBrowL   += (targetBrowL   - currBrowL)   * 0.35f;
  currBrowR   += (targetBrowR   - currBrowR)   * 0.35f;
  currEyeWL   += (targetEyeWL   - currEyeWL)   * 0.30f;
  currEyeWR   += (targetEyeWR   - currEyeWR)   * 0.30f;
  currEyeHL   += (targetEyeHL   - currEyeHL)   * 0.30f;
  currEyeHR   += (targetEyeHR   - currEyeHR)   * 0.30f;
  currEyeR    += (targetEyeR    - currEyeR)    * 0.30f;

  if (fabs(currGazeX - targetGazeX) < 0.2f) currGazeX = targetGazeX;
  if (fabs(currGazeY - targetGazeY) < 0.2f) currGazeY = targetGazeY;
  if (fabs(currEyelidL - targetEyelidL) < 0.04f) currEyelidL = targetEyelidL;
  if (fabs(currEyelidR - targetEyelidR) < 0.04f) currEyelidR = targetEyelidR;
  if (fabs(currBrowL - targetBrowL) < 0.2f) currBrowL = targetBrowL;
  if (fabs(currBrowR - targetBrowR) < 0.2f) currBrowR = targetBrowR;
  if (fabs(currEyeWL - targetEyeWL) < 0.2f) currEyeWL = targetEyeWL;
  if (fabs(currEyeWR - targetEyeWR) < 0.2f) currEyeWR = targetEyeWR;
  if (fabs(currEyeHL - targetEyeHL) < 0.2f) currEyeHL = targetEyeHL;
  if (fabs(currEyeHR - targetEyeHR) < 0.2f) currEyeHR = targetEyeHR;

  if (fabs(currGazeX - oldGx) > 0.2f || fabs(currGazeY - oldGy) > 0.2f ||
      fabs(currEyelidL - oldEl) > 0.03f || fabs(currEyelidR - oldEr) > 0.03f ||
      fabs(currBrowL - oldBl) > 0.2f   || fabs(currBrowR - oldBr) > 0.2f ||
      fabs(currEyeWL - oldWL) > 0.25f  || fabs(currEyeWR - oldWR) > 0.25f ||
      fabs(currEyeHL - oldHL) > 0.25f  || fabs(currEyeHR - oldHR) > 0.25f ||
      currentAnim == ANIM_DANCE || currentAnim == ANIM_SCAN) {
    needsRedraw = true;
  }
}

bool animatorNeedsRedraw() { return needsRedraw; }
void animatorClearRedraw() { needsRedraw = false; }

int        animatorGetGazeX()      { return (int)currGazeX; }
int        animatorGetGazeY()      { return (int)currGazeY; }
float      animatorGetEyelidL()    { return currEyelidL; }
float      animatorGetEyelidR()    { return currEyelidR; }
int        animatorGetBrowL()      { return (int)currBrowL; }
int        animatorGetBrowR()      { return (int)currBrowR; }
int        animatorGetEyeWL()      { return (int)currEyeWL; }
int        animatorGetEyeWR()      { return (int)currEyeWR; }
int        animatorGetEyeHL()      { return (int)currEyeHL; }
int        animatorGetEyeHR()      { return (int)currEyeHR; }
int        animatorGetEyeR()       { return (int)currEyeR; }
MouthShape animatorGetMouthShape() { return currentMouth; }
AnimType   animatorGetAnim()       { return currentAnim; }
LumoMood   animatorGetMood()       { return currentMood; }

bool animatorEyesOpen() {
  return (currEyelidL > 0.15f || currEyelidR > 0.15f);
}

bool animatorSmileVisible() {
  return (currentSchedule == SCHED_AWAKE);
}
