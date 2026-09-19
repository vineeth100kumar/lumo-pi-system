#pragma once
#include <Arduino.h>
#include "config.h"

void     animatorInit();
void     animatorSetMood(LumoMood mood, CharSchedule sched);
void     animatorSetAnim(AnimType anim, int8_t gx, int8_t gy, unsigned long durationMs);
void     animatorTick();
bool     animatorNeedsRedraw();
void     animatorClearRedraw();

int      animatorGetGazeX();
int      animatorGetGazeY();
float    animatorGetEyelidL();
float    animatorGetEyelidR();
int      animatorGetBrowL();
int      animatorGetBrowR();
AnimType animatorGetAnim();
bool     animatorEyesOpen();
bool     animatorSmileVisible();
