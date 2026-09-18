#include "animator.h"

static LumoMood     currentMood     = MOOD_NORMAL;
static CharSchedule currentSchedule = SCHED_AWAKE;

static bool eyesOpen    = true;
static bool needsRedraw = true;
static int  eyeOffsetX  = 0;

static unsigned long lastBlinkStart = 0;
static unsigned long blinkInterval  = 4000;
static bool          isBlinking     = false;

static unsigned long lastGazeMove   = 0;
static unsigned long gazeInterval   = 4000;

static unsigned long yawnStart      = 0;
static bool          isYawning      = false;
static unsigned long lastYawnTime   = 0;

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
  eyesOpen       = (currentSchedule != SCHED_SLEEP);
  needsRedraw    = true;
  lastBlinkStart = millis();
  blinkInterval  = getBlinkGap();
  lastGazeMove   = millis();
  gazeInterval   = random(3000, 6000);
  lastYawnTime   = millis();
}

void animatorSetMood(LumoMood mood, CharSchedule sched) {
  if (currentMood != mood || currentSchedule != sched) {
    currentMood     = mood;
    currentSchedule = sched;
    blinkInterval   = getBlinkGap();
    if (currentSchedule == SCHED_SLEEP) {
      eyesOpen = false;
    } else if (!isBlinking) {
      eyesOpen = true;
    }
    needsRedraw = true;
  }
}

void animatorTick() {
  unsigned long now = millis();

  // --- SLEEP MODE: Eyes stay closed ---
  if (currentSchedule == SCHED_SLEEP) {
    if (eyesOpen) {
      eyesOpen = false;
      needsRedraw = true;
    }
    return;
  }

  // --- BLINK LOGIC ---
  if (!isBlinking) {
    if (now - lastBlinkStart >= blinkInterval) {
      isBlinking     = true;
      lastBlinkStart = now;
      eyesOpen       = false;
      needsRedraw    = true;
    }
  } else {
    // Eyelids closed for 140ms
    if (now - lastBlinkStart >= 140) {
      isBlinking     = false;
      eyesOpen       = (currentSchedule != SCHED_SLEEP);
      lastBlinkStart = now;
      blinkInterval  = getBlinkGap();
      needsRedraw    = true;
    }
  }

  // --- GAZE MICRO-MOVEMENT ---
  if (now - lastGazeMove >= gazeInterval) {
    lastGazeMove = now;
    gazeInterval = random(3000, 6500);
    int choices[3] = {-4, 0, 4};
    int nextOffset = choices[random(0, 3)];
    if (nextOffset != eyeOffsetX) {
      eyeOffsetX  = nextOffset;
      needsRedraw = true;
    }
  }

  // --- YAWN (When BORED) ---
  if (currentMood == MOOD_BORED && currentSchedule != SCHED_SLEEP) {
    if (!isYawning && (now - lastYawnTime >= 12000)) {
      isYawning    = true;
      yawnStart    = now;
      lastYawnTime = now;
      needsRedraw  = true;
    }
    if (isYawning && (now - yawnStart >= 2500)) {
      isYawning    = false;
      lastYawnTime = now;
      needsRedraw  = true;
    }
  } else {
    if (isYawning) {
      isYawning   = false;
      needsRedraw = true;
    }
  }
}

bool animatorNeedsRedraw()   { return needsRedraw; }
void animatorClearRedraw()   { needsRedraw = false; }
int  animatorGetEyeOffsetX() { return eyeOffsetX; }
bool animatorEyesOpen()      { return eyesOpen; }
bool animatorSmileVisible()  { return (currentSchedule == SCHED_AWAKE); }
bool animatorYawning()       { return isYawning; }
