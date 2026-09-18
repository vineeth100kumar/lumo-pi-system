#pragma once
#include "config.h"

void wsInit(LumoState& state);
void wsConnect();
void wsPoll();
bool wsConnected();
void wsSend(const char* json);
