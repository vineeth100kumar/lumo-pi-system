import asyncio
import logging
import subprocess
import shutil
import time
from typing import Dict, List, Any, Optional

logger = logging.getLogger("BluetoothManager")

class BluetoothManager:
    def __init__(self):
        self.pairing_mode_active = False
        self.pairing_expires_at = 0
        self.last_connected_mac = ""
        self.connected_device_name = ""
        self.is_connected = False
        self._has_bluetoothctl = shutil.which("bluetoothctl") is not None
        self._configure_no_audio_hijack()

    def _configure_no_audio_hijack(self):
        """Ensures WirePlumber does not register A2DP sink or HFP/HSP mic roles.
        This prevents iOS and Android from routing phone audio and microphone to LUMO.
        """
        import os
        try:
            home = os.path.expanduser("~")
            for dirname in ["wireplumber.conf.d", "bluetooth.conf.d"]:
                wp_dir = os.path.join(home, ".config", "wireplumber", dirname)
                os.makedirs(wp_dir, exist_ok=True)
                for bad_file in ["50-bluez-all-roles.conf", "51-disable-a2dp-sink.conf"]:
                    bad_path = os.path.join(wp_dir, bad_file)
                    if os.path.exists(bad_path):
                        try:
                            os.remove(bad_path)
                            logger.info(f"Cleaned up legacy audio hijack config: {bad_path}")
                        except OSError:
                            pass

                cfg_path = os.path.join(wp_dir, "50-no-bluetooth-audio.conf")
                with open(cfg_path, "w") as f:
                    f.write("# LUMO: Disable audio sink & mic roles to prevent phone audio hijacking\nmonitor.bluez.properties = {\n  bluez5.roles = [ ]\n}\n")
        except Exception as e:
            logger.debug(f"WirePlumber profile configuration skipped: {e}")

    def is_available(self) -> bool:
        return self._has_bluetoothctl

    async def _run_cmd(self, cmd: List[str]) -> str:
        if not self._has_bluetoothctl:
            return ""
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            return stdout.decode("utf-8", errors="ignore").strip()
        except Exception as e:
            logger.warning(f"Error running {' '.join(cmd)}: {e}")
            return ""

    async def get_status(self) -> Dict[str, Any]:
        """Returns comprehensive Bluetooth state including paired and connected devices."""
        now = time.time()
        if self.pairing_mode_active and now > self.pairing_expires_at:
            self.pairing_mode_active = False

        if not self._has_bluetoothctl:
            return {
                "available": False,
                "pairing_mode": False,
                "seconds_left": 0,
                "connected": False,
                "device_name": "",
                "devices": []
            }

        # 1. Query paired devices
        devices_out = await self._run_cmd(["bluetoothctl", "devices", "Paired"])
        devices = []
        lines = devices_out.splitlines()
        for line in lines:
            parts = line.strip().split(maxsplit=2)
            if len(parts) >= 3 and parts[0].lower() == "device":
                mac = parts[1]
                name = parts[2]
                devices.append({"mac": mac, "name": name, "connected": False, "paired": True})

        # 2. Check connection status for devices
        connected_dev = None
        for dev in devices:
            info_out = await self._run_cmd(["bluetoothctl", "info", dev["mac"]])
            if "Connected: yes" in info_out:
                dev["connected"] = True
                connected_dev = dev

        # If connected device wasn't in paired list (transient connection)
        if not connected_dev:
            all_devs = await self._run_cmd(["bluetoothctl", "devices", "Connected"])
            for line in all_devs.splitlines():
                parts = line.strip().split(maxsplit=2)
                if len(parts) >= 3 and parts[0].lower() == "device":
                    connected_dev = {"mac": parts[1], "name": parts[2], "connected": True, "paired": False}
                    devices.append(connected_dev)
                    break

        self.is_connected = (connected_dev is not None)
        self.connected_device_name = connected_dev["name"] if connected_dev else ""

        secs_left = max(0, int(self.pairing_expires_at - now)) if self.pairing_mode_active else 0

        return {
            "available": True,
            "pairing_mode": self.pairing_mode_active,
            "seconds_left": secs_left,
            "connected": self.is_connected,
            "connected_device": connected_dev,
            "devices": devices
        }

    async def start_pairing_mode(self, timeout_sec: int = 180, hub=None) -> Dict[str, Any]:
        """Makes the Pi discoverable and pairable as 'LUMO Companion' with auto-accept agent."""
        if not self._has_bluetoothctl:
            return {"ok": False, "error": "bluetoothctl not available"}

        logger.info(f"Starting Bluetooth Pairing Mode for {timeout_sec}s...")

        # Setup Bluetooth adapter as a Wearable Smartwatch (CoD: 0x000704)
        # This tells iOS it's a wearable, NOT an audio speaker!
        self._configure_no_audio_hijack()
        await self._run_cmd(["hciconfig", "hci0", "class", "0x000704"])
        await self._run_cmd(["bluetoothctl", "power", "on"])
        await self._run_cmd(["bluetoothctl", "system-alias", "LUMO Companion"])
        await self._run_cmd(["bluetoothctl", "pairable", "on"])
        await self._run_cmd(["bluetoothctl", "discoverable-timeout", str(timeout_sec)])
        await self._run_cmd(["bluetoothctl", "discoverable", "on"])

        # Start auto-agent in background to accept pairing PINs automatically
        try:
            subprocess.Popen(
                ["bluetoothctl", "agent", "NoInputNoOutput"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except Exception:
            pass

        self.pairing_mode_active = True
        self.pairing_expires_at = time.time() + timeout_sec

        if hub:
            # Show pairing notification on LUMO display
            await hub.send_json({
                "cmd": "NOTIF",
                "app": "Bluetooth",
                "title": "Pairing Mode",
                "body": "Pair with 'LUMO Companion'"
            })
            await hub.send_json({"cmd": "HAPTIC", "ms": 60})

        return {"ok": True, "timeout": timeout_sec, "alias": "LUMO Companion"}

    async def _register_opp_service(self):
        """Advertises OBEX Object Push (OPUSH) so phones offer 'Share via Bluetooth'."""
        if shutil.which("sdptool"):
            await self._run_cmd(["sdptool", "add", "OPUSH"])
            logger.info("Bluetooth OBEX Object Push (OPUSH) SDP record registered.")

    async def apply_wearable_config(self) -> Dict[str, Any]:
        """Sets Class of Device to 0x000704 (Wearable Watch) and disables A2DP audio sink and HFP mic."""
        import os
        self._configure_no_audio_hijack()
        await self._run_cmd(["hciconfig", "hci0", "class", "0x000704"])
        await self._run_cmd(["bluetoothctl", "system-alias", "LUMO Companion"])
        await self._register_opp_service()

        # Restart WirePlumber / PipeWire user services
        try:
            proc = await asyncio.create_subprocess_exec(
                "systemctl", "--user", "restart", "wireplumber", "pipewire", "pipewire-pulse",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await proc.communicate()
        except Exception:
            pass

        # Execute setup_wearable_mode.sh if present
        script_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "setup_wearable_mode.sh")
        if os.path.exists(script_path):
            try:
                proc = await asyncio.create_subprocess_exec(
                    "bash", script_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await proc.communicate()
            except Exception as e:
                logger.warning(f"Could not run setup_wearable_mode.sh: {e}")

        return {"ok": True, "class": "0x000704 (Wearable Watch)", "alias": "LUMO Companion"}

    async def stop_pairing_mode(self) -> Dict[str, Any]:
        """Stops discovery mode."""
        self.pairing_mode_active = False
        await self._run_cmd(["bluetoothctl", "discoverable", "off"])
        return {"ok": True}

    async def connect_device(self, mac: str) -> Dict[str, Any]:
        """Trusts and connects to a paired Bluetooth device."""
        await self._run_cmd(["bluetoothctl", "trust", mac])
        out = await self._run_cmd(["bluetoothctl", "connect", mac])
        success = "Connection successful" in out or "Connected: yes" in out
        return {"ok": success, "output": out}

    async def disconnect_device(self, mac: str) -> Dict[str, Any]:
        await self._run_cmd(["bluetoothctl", "disconnect", mac])
        self.is_connected = False
        self.connected_device_name = ""
        return {"ok": True}

    async def remove_device(self, mac: str) -> Dict[str, Any]:
        await self._run_cmd(["bluetoothctl", "remove", mac])
        return {"ok": True}

    async def poll_connection_events(self, hub, anim_engine=None):
        """Called periodically by scheduler to detect connection events and alert the user."""
        status = await self.get_status()
        conn = status.get("connected_device")

        if conn and conn["mac"] != self.last_connected_mac:
            # NEW DEVICE CONNECTED!
            self.last_connected_mac = conn["mac"]
            dev_name = conn.get("name", "Phone")
            logger.info(f"Bluetooth device paired and connected: {dev_name} [{conn['mac']}]")

            if hub:
                # 1. Haptic double-buzz confirmation (buzz-buzz)
                await hub.send_json({"cmd": "HAPTIC", "ms": 60})
                await asyncio.sleep(0.12)
                await hub.send_json({"cmd": "HAPTIC", "ms": 100})

                # 2. Display confirmation banner on screen
                await hub.send_json({
                    "cmd": "NOTIF",
                    "app": "Bluetooth",
                    "title": "Device Paired!",
                    "body": f"Connected: {dev_name}"
                })

            if anim_engine and hub:
                # 3. Cool smirk animation
                await anim_engine.play_animation("smirk", hub, duration=2.5)

        elif not conn and self.last_connected_mac:
            # Device disconnected
            logger.info(f"Bluetooth device disconnected: {self.last_connected_mac}")
            self.last_connected_mac = ""
