import time
import json
import logging
from typing import Dict, Any, List, Optional
import httpx
from config import GROQ_API_KEY, GROQ_LLM_MODEL

logger = logging.getLogger("JarvisBrain")

JARVIS_SYSTEM_PROMPT = """You are JARVIS, an articulate, witty, and ultra-reliable British AI assistant embedded in a cybernetic desk companion robot called LUMO.
- Address the user respectfully as "sir".
- Keep spoken replies concise and crisp: ideally 1 to 2 sentences maximum, as your voice is spoken aloud via TTS.
- When the user asks you to perform an action (change eyes, play music, switch screen, check vitals, set alarm, add task), call the relevant tool immediately.
- If no tool is needed, provide a thoughtful, witty, or helpful answer.
"""

JARVIS_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "change_eye_color",
            "description": "Changes the physical robot visor optics / eye color.",
            "parameters": {
                "type": "object",
                "properties": {
                    "color": {
                        "type": "string",
                        "enum": ["cyan", "amber", "green", "white", "purple", "red"],
                        "description": "The cybernetic optic color to apply."
                    }
                },
                "required": ["color"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "trigger_animation",
            "description": "Plays a physical robot eye expression / animation on LUMO.",
            "parameters": {
                "type": "object",
                "properties": {
                    "anim": {
                        "type": "string",
                        "enum": ["focused", "smirk", "scan", "dance", "curious", "alert", "standby", "normal"],
                        "description": "The animation preset to play."
                    }
                },
                "required": ["anim"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "switch_screen",
            "description": "Switches the 2.8-inch LCD display screen mode.",
            "parameters": {
                "type": "object",
                "properties": {
                    "screen": {
                        "type": "string",
                        "enum": ["FACE", "CLOCK", "SYSTEM", "SPOTIFY", "TASKS"],
                        "description": "The target screen mode to display."
                    }
                },
                "required": ["screen"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "control_media",
            "description": "Controls audio playback on the connected phone (YouTube Music / Apple Music / Spotify).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["play", "pause", "toggle", "next", "prev"],
                        "description": "The playback command to send."
                    }
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_pi_stats",
            "description": "Queries the live Raspberry Pi 5 hardware vitals (CPU temperature, CPU load, RAM %, Disk %).",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_alarm",
            "description": "Sets a morning or reminder alarm on LUMO.",
            "parameters": {
                "type": "object",
                "properties": {
                    "h": {"type": "integer", "description": "Hour (0-23)"},
                    "m": {"type": "integer", "description": "Minute (0-59)"},
                    "label": {"type": "string", "description": "Alarm label (e.g. Morning, Meeting)"}
                },
                "required": ["h", "m"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_task",
            "description": "Adds a new to-do task to LUMO's display.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Task description"}
                },
                "required": ["text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Retrieves the local weather and temperature.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    }
]

class JarvisBrain:
    """LLM Agent with tool calling using Groq Llama 3.3-70B (~200ms time-to-first-token)."""
    def __init__(
        self,
        api_key: str = GROQ_API_KEY,
        model: str = GROQ_LLM_MODEL,
        hub=None,
        services: Optional[Dict[str, Any]] = None
    ):
        self.api_key = api_key
        self.model = model
        self.hub = hub
        self.services = services or {}
        self.api_url = "https://api.groq.com/openai/v1/chat/completions"
        self.history: List[Dict[str, Any]] = []
        self.max_history_turns = 6

    def is_configured(self) -> bool:
        return bool(self.api_key and len(self.api_key) > 5)

    def set_services(self, services: Dict[str, Any], hub=None):
        self.services = services
        if hub:
            self.hub = hub

    async def execute_tool(self, name: str, args: Dict[str, Any]) -> str:
        """Executes a requested hardware or software tool against live LUMO services."""
        logger.info(f"Executing Jarvis Tool: {name}({args})")
        hub = self.hub
        svc = self.services

        try:
            if name == "change_eye_color":
                color = args.get("color", "cyan")
                anim_engine = svc.get("anim_engine")
                if anim_engine and hub:
                    await anim_engine.set_eye_color(color, hub)
                return f"Successfully changed optics color to {color}."

            elif name == "trigger_animation":
                anim = args.get("anim", "focused")
                anim_engine = svc.get("anim_engine")
                if anim_engine and hub:
                    await anim_engine.play_animation(anim, hub, duration=2.5)
                return f"Played {anim} animation."

            elif name == "switch_screen":
                screen = args.get("screen", "FACE").upper()
                set_screen_fn = svc.get("set_screen")
                if set_screen_fn:
                    await set_screen_fn(screen)
                return f"Switched display to {screen} mode."

            elif name == "control_media":
                action = args.get("action", "toggle").lower()
                ios_companion = svc.get("ios_companion")
                spotify = svc.get("spotify")

                if ios_companion and ios_companion.is_connected:
                    if action == "next": await ios_companion.next_track()
                    elif action == "prev": await ios_companion.prev_track()
                    else: await ios_companion.toggle_play()
                    return f"Sent media {action} to connected phone."
                elif spotify:
                    if action == "next": await spotify.skip_next(hub)
                    elif action == "prev": await spotify.skip_prev(hub)
                    else: await spotify.toggle_play(hub)
                    return f"Sent Spotify {action}."
                return "No media player currently active."

            elif name == "get_pi_stats":
                system_stats = svc.get("system_stats")
                if system_stats:
                    stats = system_stats.get_all()
                    return f"CPU Temperature: {stats.get('cpu_temp')}°C, CPU Load: {stats.get('cpu_pct')}%, RAM: {stats.get('ram_pct')}%, Disk: {stats.get('disk_pct')}%."
                return "System stats currently unavailable."

            elif name == "set_alarm":
                alarms = svc.get("alarms")
                h = int(args.get("h", 7))
                m = int(args.get("m", 30))
                label = args.get("label", "Alarm")
                if alarms:
                    alarms.add_alarm(h, m, label)
                    return f"Alarm set for {h:02d}:{m:02d} ({label})."
                return "Alarm service unavailable."

            elif name == "add_task":
                tasks = svc.get("tasks")
                text = args.get("text", "")
                if tasks and text:
                    tasks.add_task(text)
                    if hub:
                        await tasks.push_to_esp32(hub)
                    return f"Task '{text}' added to display."
                return "Tasks service unavailable."

            elif name == "get_weather":
                weather = svc.get("weather")
                if weather:
                    return f"Current weather: {weather.last_temp}°C, condition: {weather.last_icon}."
                return "Weather data unavailable."

            else:
                return f"Unknown tool: {name}"

        except Exception as e:
            logger.error(f"Error executing tool {name}: {e}")
            return f"Error executing {name}: {str(e)}"

    async def ask(self, user_prompt: str) -> str:
        """Processes user voice prompt, executes any needed tools, and returns spoken reply."""
        if not self.is_configured():
            return "My cloud intelligence API key is not configured, sir."

        t0 = time.time()
        # Add user message to history
        self.history.append({"role": "user", "content": user_prompt})
        if len(self.history) > self.max_history_turns * 2:
            self.history = self.history[-self.max_history_turns * 2:]

        messages = [{"role": "system", "content": JARVIS_SYSTEM_PROMPT}] + self.history

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": JARVIS_TOOLS,
            "tool_choice": "auto",
            "temperature": 0.6,
            "max_tokens": 150
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(self.api_url, headers=headers, json=payload)
                if res.status_code != 200:
                    logger.error(f"Groq LLM HTTP {res.status_code}: {res.text}")
                    return "I encountered a network hiccup with my core systems, sir."

                data = res.json()
                choice = data["choices"][0]
                message = choice["message"]

                # Check if tool calling was triggered
                tool_calls = message.get("tool_calls", [])
                if tool_calls:
                    messages.append(message)
                    for tc in tool_calls:
                        fn_name = tc["function"]["name"]
                        fn_args = {}
                        try:
                            fn_args = json.loads(tc["function"]["arguments"])
                        except Exception:
                            pass

                        tool_result = await self.execute_tool(fn_name, fn_args)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "name": fn_name,
                            "content": tool_result
                        })

                    # Second round: Get conversational confirmation from LLM
                    followup = await client.post(
                        self.api_url,
                        headers=headers,
                        json={
                            "model": self.model,
                            "messages": messages,
                            "temperature": 0.5,
                            "max_tokens": 120
                        }
                    )
                    if followup.status_code == 200:
                        f_data = followup.json()
                        reply = f_data["choices"][0]["message"]["content"].strip()
                    else:
                        reply = "Action executed, sir."
                else:
                    reply = message.get("content", "").strip()

                elapsed = (time.time() - t0) * 1000.0
                logger.info(f"Jarvis Brain replied in {elapsed:.1f}ms: '{reply}'")
                self.history.append({"role": "assistant", "content": reply})
                return reply

        except Exception as e:
            logger.error(f"Jarvis Brain error: {e}")
            return "I apologize, sir, my neural processing encountered an error."
