#pragma once
#include <Arduino.h>
#include "config.h"

void wsInit(LumoState& state);
void wsConnect();
void wsPoll();
bool wsConnected();
void wsSend(const char* json);
