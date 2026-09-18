import logging
import httpx
from config import WEATHER_LAT, WEATHER_LON

logger = logging.getLogger("WeatherService")

class WeatherService:
    def __init__(self):
        self.last_temp = None
        self.last_icon = None

    def _code_to_icon(self, code: int) -> str:
        if code == 0:
            return "clear"
        if 1 <= code <= 3 or code in (45, 48):
            return "cloudy"
        if (51 <= code <= 67) or (80 <= code <= 82):
            return "rain"
        if (71 <= code <= 77) or code in (85, 86):
            return "snow"
        if 95 <= code <= 99:
            return "storm"
        return "clear"

    async def poll(self, hub) -> None:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={WEATHER_LAT}&longitude={WEATHER_LON}&current_weather=true"
        )
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                res = await client.get(url)
                if res.status_code == 200:
                    data = res.json().get("current_weather", {})
                    temp = round(float(data.get("temperature", 0.0)), 1)
                    code = int(data.get("weathercode", 0))
                    icon = self._code_to_icon(code)

                    if temp != self.last_temp or icon != self.last_icon:
                        self.last_temp = temp
                        self.last_icon = icon
                        await hub.send_json({
                            "cmd": "WEATHER",
                            "temp_c": temp,
                            "icon": icon
                        })
                        logger.info(f"Weather updated: {temp}°C, {icon}")
        except Exception as e:
            logger.warning(f"Error fetching weather: {e}")
