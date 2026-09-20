# LUMO: Raspberry Pi 5 Controlled Smart Companion System

A distributed IoT smart desk clock and companion system featuring:
- **Raspberry Pi 5 ("The Brain")**: Handles Spotify API, Open-Meteo weather, multi-alarm scheduling, task syncing, circadian emotion logic, and serves a modern glassmorphic web dashboard.
- **ESP32-C3 ("The Display Node")**: Operates as a zero-lag, dedicated peripheral and display driver pushing pixels over 40 MHz SPI to a 2.8" ILI9341 display with dirty-rectangle redraws, WS2812B NeoPixel lighting, and an active-low haptic buzzer.

---

## 1. Hardware Pinout & Wiring (ESP32-C3)

| Component | Pin | Notes |
| :--- | :--- | :--- |
| **TFT Display CS** | GPIO 8 | Hardware SPI Chip Select |
| **TFT Display DC** | GPIO 7 | Data / Command Select |
| **TFT Display SCK** | GPIO 4 | Hardware SPI Clock |
| **TFT Display MOSI**| GPIO 6 | Hardware SPI Data Out |
| **TFT Display VCC** | 3.3V / 5V | Depending on module voltage regulator |
| **TFT Display GND** | GND | Common Ground |
| **Button Ladder** | GPIO 1 (ADC) | 5-way resistor ladder: OK (~0.15V), UP (~0.60V), DOWN (~0.22V), LEFT (~3.30V), RIGHT (~0.33V) |
| **NeoPixel Ring** | GPIO 10 | 6x WS2812B RGB LEDs |
| **Haptic Buzzer** | GPIO 9 | Active-low PWM (50 kHz silent haptic click or audio alarm) |

*Note: Battery monitoring has been completely omitted. Power the ESP32 directly via USB-C.*

---

## 2. ESP32-C3 Firmware Setup

### Arduino IDE Libraries Required:
Install the following via the Arduino IDE Library Manager:
1. `Adafruit ILI9341` (by Adafruit)
2. `Adafruit GFX Library` (by Adafruit)
3. `Adafruit NeoPixel` (by Adafruit)
4. `ArduinoWebsockets` (by Gil Maimon)
5. `ArduinoJson` (v7 by Benoit Blanchon)

*(Note: `TJpg_Decoder` is not needed on the ESP32. The Raspberry Pi converts all Spotify album art directly to raw RGB565 bitmaps before transmission).*

### Flashing:
1. Open `esp32_client/esp32_client.ino` in the Arduino IDE.
2. In `config.h`, check and update your Wi-Fi credentials (`WIFI_SSID` and `WIFI_PASS`).
3. Select board: **ESP32C3 Dev Module**.
4. Set Flash Mode to **DIO** and CPU Frequency to **160MHz**.
5. Upload the sketch to your ESP32-C3.

---

## 3. Raspberry Pi 5 Server Setup

### Installation:
1. Copy the `rpi_server` folder to your Raspberry Pi 5 (e.g. `/home/pi/lumo_pi_system/rpi_server`).
2. Create and activate a Python virtual environment:
   ```bash
   cd /home/pi/lumo_pi_system/rpi_server
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   nano .env
   ```
4. Enter your Spotify credentials and location coordinates.

### Running Manually:
```bash
python3 main.py
```
- Web dashboard will be live at: `http://<your-pi-ip>:8080` (or `http://lumo.local:8080`).
- WebSocket server for the ESP32 will listen on: `ws://0.0.0.0:8765`.

### Setting up Auto-Start Service (systemd):
```bash
sudo cp lumo.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable lumo.service
sudo systemctl start lumo.service
```

---

## 4. Shared Task Manager (Sage)

Tasks, reminders and alarms are not stored on Lumo. They live in Sage, the task
manager running on the same Pi, so a task added at the desk clock is on the
phone and a reminder set on the phone rings at the desk.

Lumo talks to Sage over the loopback address rather than opening its database,
which means Sage's own rules still apply and its app refreshes the moment
anything changes. Neither project imports a line of the other's code.

| What happens | Where it goes |
| :--- | :--- |
| "Jarvis, add a task" | Sage's capture engine, so times and dates are understood |
| Task list on the display and dashboard | Sage's open tasks, soonest first |
| Alarms | Sage reminders tagged `alarm` |
| A Sage reminder falling due | A buzz and a notification card on the face |

### Setup

The only thing Lumo needs is Sage's API key, and it does not get its own copy.
Sage keeps the key in `/etc/sage/sage.env`, which is readable only by root, so
Lumo's service file carries the same `EnvironmentFile` line Sage's does and
systemd passes the value down:

```ini
# already present in lumo.service
EnvironmentFile=-/etc/sage/sage.env
```

If you installed the service before this change, copy the unit again:

```bash
sudo cp lumo.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart lumo.service
```

Then check the connection:

```bash
cd /home/pi/lumo_pi_system/rpi_server
venv/bin/python test_sage.py
```

Running `main.py` by hand instead of through systemd? Put the key in `.env` as
`SAGE_API_KEY` — it is the same value Sage uses, and the app asks for it on
each device too.

Sage being down is not fatal: the display keeps showing the last list it saw,
and Lumo reconnects on its own.

---

## 5. Spotify Developer App Setup

1. Go to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) and create an app.
2. In your app settings, add `http://localhost:8888/callback` as a **Redirect URI**.
3. Note your **Client ID** and **Client Secret**.
4. To generate your `SPOTIFY_REFRESH_TOKEN`, run your local OAuth authorization flow requesting scopes:
   - `user-read-playback-state`
   - `user-read-currently-playing`
   - `user-modify-playback-state`
5. Paste `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, and `SPOTIFY_REFRESH_TOKEN` into your `.env` file.

---

## 6. Screen Navigation (Physical Controls)

- **From Face Screen**:
  - `RIGHT` -> Desk Clock Screen
  - `LEFT`  -> Tasks List Screen
  - `OK`    -> Spotify Music Card Screen
- **From Clock Screen**:
  - `LEFT`  -> Tasks Screen
  - `OK`    -> Face Screen
  - `RIGHT` -> Spotify Screen
- **From Spotify Screen**:
  - `LEFT`  -> Clock Screen
  - `OK`    -> Play / Pause toggle
  - `RIGHT` -> Next Track
- **During Alarm Ringing**:
  - Pressing any button dismisses the alarm.
