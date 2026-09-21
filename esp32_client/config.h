#pragma once
#include <Arduino.h>

// ===================== PINS =====================
#define TFT_CS        8
#define TFT_DC        7
#define BUTTON_PIN    1
#define BUZZER_PIN    9    // Active-LOW haptic/buzzer
#define NEOPIXEL_PIN  10
#define NUMPIXELS     6

// ===================== WIFI =====================
#define WIFI_SSID  "TP-Link_34E8"
#define WIFI_PASS  "19720883"

// ===================== PI SERVER =====================
#define PI_HOSTNAME  "192.168.0.149"
#define PI_WS_PORT   8765
#define PI_WS_PATH   "/"

// ===================== NTP / TIMEZONE =====================
#define GMT_OFFSET_SEC  (5 * 3600 + 30 * 60)
#define DAYLIGHT_OFFSET 0
#define NTP_SERVER1     "pool.ntp.org"
#define NTP_SERVER2     "time.nist.gov"

// ===================== HAPTICS =====================
#define HAPTIC_FREQ  50000
#define HAPTIC_RES   8

// ===================== BUTTON VOLTAGE THRESHOLDS =====================
#define V_OK    0.15f
#define V_UP    0.60f
#define V_DOWN  0.22f
#define V_LEFT  3.30f
#define V_RIGHT 0.33f
#define V_TOL   0.05f

// ===================== FIRMWARE =====================
#define FW_VERSION "1.4.0"

// ===================== ENUMS =====================
enum Button       { BTN_NONE, BTN_OK, BTN_UP, BTN_DOWN, BTN_LEFT, BTN_RIGHT };
enum ScreenMode   { SCREEN_FACE, SCREEN_CLOCK, SCREEN_SYSTEM, SCREEN_SPOTIFY, SCREEN_TASKS, SCREEN_ALARM, SCREEN_CONNECTING, SCREEN_MEMORY };
enum LumoMood     { MOOD_NORMAL, MOOD_HAPPY, MOOD_BORED, MOOD_SAD, MOOD_EXCITED };
enum CharSchedule { SCHED_AWAKE, SCHED_DROWSY, SCHED_SLEEP };
enum NeoMode      { NEO_WARM, NEO_COLOR, NEO_BREATHE, NEO_OFF, NEO_ALARM };
enum AnimType     { ANIM_NORMAL, ANIM_FOCUSED, ANIM_SMIRK, ANIM_SCAN, ANIM_DANCE, ANIM_ALERT, ANIM_CURIOUS, ANIM_STANDBY, ANIM_LOOK };
enum MouthShape   { MOUTH_SMILE, MOUTH_SMIRK, MOUTH_FOCUSED, MOUTH_SAD, MOUTH_SURPRISED, MOUTH_NEUTRAL };

// ===================== CENTRAL STATE STRUCT =====================
struct LumoState {
  uint8_t  h = 0, m = 0;
  char     weekday[8] = "---";
  char     date[12]   = "--";
  float    temp_c = 0.0f;
  char     weather_icon[12] = "clear";
  char     sp_title[64]  = "";
  char     sp_artist[64] = "";
  uint32_t sp_progress_ms = 0;
  uint32_t sp_duration_ms = 0;
  bool     sp_playing = false;
  LumoMood     mood     = MOOD_NORMAL;
  CharSchedule schedule = SCHED_AWAKE;
  NeoMode  neo_mode       = NEO_WARM;
  uint8_t  neo_brightness = 40;
  uint16_t neo_hue        = 0;
  char    tasks[5][96];
  uint8_t task_count = 0;
  bool    alarm_ringing = false;
  uint8_t alarm_h = 7, alarm_m = 0;

  // Pi 5 System Vitals
  float   cpu_temp = 0.0f;
  uint8_t cpu_pct  = 0;
  uint8_t ram_pct  = 0;
  uint8_t disk_pct = 0;

  // Cybernetic Face & Animation State
  AnimType anim_type = ANIM_NORMAL;
  uint16_t eye_color = 0x073F; // Default Electric Cyan
  int8_t   gaze_x    = 0;
  int8_t   gaze_y    = 0;

  // Phone Notifications Overlay
  bool          notif_active = false;
  char          notif_app[20]   = "";
  char          notif_title[28] = "";
  char          notif_body[64]  = "";
  unsigned long notif_start     = 0;

  // JARVIS Voice Companion State
  char          voice_state[16]    = "IDLE";
  char          voice_subtitle[48] = "";
  float         voice_volume       = 0.0f;

  // Memories Photo Frame
  char          mem_caption[24]    = "";

  // Dirty flags
  bool       flag_spotify_changed = false;
  bool       flag_tasks_changed   = false;
  bool       flag_system_changed  = false;
  bool       flag_anim_changed    = false;
  bool       flag_screen_switch   = false;
  bool       flag_voice_changed   = false;
  bool       flag_memory_changed  = false;
  ScreenMode next_screen          = SCREEN_FACE;
};
