#pragma once
#include "config.h"

void animatorInit();
void animatorSetMood(LumoMood mood, CharSchedule sched);
void animatorTick();
bool animatorNeedsRedraw();
void animatorClearRedraw();

int  animatorGetEyeOffsetX();
bool animatorEyesOpen();
bool animatorSmileVisible();
bool animatorYawning();
