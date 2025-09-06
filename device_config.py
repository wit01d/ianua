import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from cache_device_connection import DeviceConnectionClient


class DeviceConfigurator:
    def __init__(self):
        self.client = DeviceConnectionClient(auto_start_service=True)
        self.target_models = [
            "SM-G973",
            "SM-G975",
            "ONEPLUS A6000",
            "ONEPLUS A6003",
            "ONEPLUS A6010",
            "ONEPLUS A6013",
        ]
        self.settings_commands = self.get_settings_commands()

    def get_settings_commands(self):
        commands = [
            ("settings put system accelerometer_rotation 0", "Disable auto-rotation"),
            ("settings put system user_rotation 0", "Set orientation to portrait"),
            (
                "settings put global window_animation_scale 0",
                "Disable window animation",
            ),
            (
                "settings put global transition_animation_scale 0",
                "Disable transition animation",
            ),
            (
                "settings put global animator_duration_scale 0",
                "Disable animator duration",
            ),
            ("settings put secure show_touches 1", "Enable show taps"),
            ("settings put system pointer_location 1", "Enable pointer location"),
            (
                "settings put global stay_on_while_plugged_in 7",
                "Stay awake while charging",
            ),
            ("settings put global adb_enabled 1", "Enable ADB"),
            (
                "settings put global development_settings_enabled 1",
                "Enable developer options",
            ),
            ("setprop persist.service.adb.enable 1", "Enable rooted debugging"),
            (
                "settings put global verifier_verify_adb_installs 1",
                "Verify apps over USB",
            ),
            (
                "settings put global mobile_data_always_on 0",
                "Disable mobile data always active",
            ),
            (
                "settings put global force_resizable_activities 1",
                "Force resizable activities",
            ),
            ("settings put secure ui_night_mode 2", "Enable dark theme"),
            ("settings put system font_scale 0.8", "Set font scale to 0.8"),
            ("settings put system screen_brightness_mode 0", "Manual brightness mode"),
            (
                "settings put system screen_brightness 12",
                "Set brightness to 5% (12/255)",
            ),
            ("settings put secure lockscreen.disabled 1", "Disable lock screen"),
            (
                'locksettings clear --old "" 2>/dev/null || locksettings set-disabled true 2>/dev/null || true',
                "Clear screen lock",
            ),
            ("wm density 200", "Reset display density to default"),
            ('settings put global display_size_forced ""', "Clear forced display size"),
            (
                'setprop persist.vendor.display.defaultres ""',
                "Clear default resolution property",
            ),
            ("setprop persist.sys.usb.config mtp,adb", "Set USB to MTP/data transfer"),
            ("settings put global adb_wifi_enabled 0", "Disable WiFi debugging"),
            (
                "settings put secure location_indicators_enabled 1",
                "Enable location indicator",
            ),
            (
                "settings put secure location_indicator_settings_enabled 1",
                "Enable location settings indicator",
            ),
            ("setprop debug.hwui.force_dark true", "Force dark mode in apps"),
            ("cmd uimode night yes", "Enable system dark mode"),
            ("input keyevent 82", "Unlock device (menu key)"),
            ("input keyevent 3", "Press home button"),
        ]

        return commands

    def get_connected_devices(self):
        print("📱 Discovering connected devices...")
        result = self.client.discover_devices()

        if result.get("status") != "success":
            print(f"❌ Failed to discover devices: {result.get('message')}")
            return {}

        devices = result.get("data", {})
        print(f"✔ Found {len(devices)} total device(s)")

        filtered_devices = {}
        for serial, info in devices.items():
            model = info.get("model", "").upper()
            for target in self.target_models:
                if target.upper() in model:
                    filtered_devices[serial] = info
                    print(f"  ✔ Target device found: {serial} ({info.get('model')})")
                    break

        if not filtered_devices:
            print("⚠ No Samsung S10 or OnePlus 6 devices found")
            print("  Available devices:")
            for serial, info in devices.items():
                print(f"    - {serial}: {info.get('model')}")

        return filtered_devices

    def execute_command_threaded(
        self, serial, command, description, results_dict, lock
    ):
        try:
            result = self.client.execute_action(serial, "shell", command=command)

            with lock:
                if result.get("status") == "success":
                    results_dict["success"].append((command, description))
                else:
                    results_dict["failed"].append(
                        (command, description, result.get("message"))
                    )
        except Exception as e:
            with lock:
                results_dict["failed"].append((command, description, str(e)))

    def configure_device(self, serial, device_info):
        print(f"\n🔧 Configuring {serial} ({device_info.get('model')})...")

        results_dict = {"success": [], "failed": []}
        lock = threading.Lock()
        threads = []

        batch_size = 5
        command_batches = [
            self.settings_commands[i : i + batch_size]
            for i in range(0, len(self.settings_commands), batch_size)
        ]

        for batch_num, batch in enumerate(command_batches, 1):
            print(
                f"  📦 Processing batch {batch_num}/{len(command_batches)} ({len(batch)} commands)..."
            )

            batch_threads = []
            for command, description in batch:
                thread = threading.Thread(
                    target=self.execute_command_threaded,
                    args=(serial, command, description, results_dict, lock),
                )
                thread.start()
                batch_threads.append(thread)

            for thread in batch_threads:
                thread.join()

            with lock:
                print(
                    f"    ✔ Completed: {len(results_dict['success'])} | ✗ Failed: {len(results_dict['failed'])}"
                )

        try:
            self.client.execute_action(
                serial,
                "shell",
                command="am broadcast -a com.android.intent.action.CONFIGURATION_CHANGED",
            )
            print(f"  ✔ Broadcasted configuration change")
        except:
            pass

        success_count = len(results_dict["success"])
        failed_commands = results_dict["failed"]

        print(f"\n📊 Summary for {serial}:")
        print(
            f"  ✔ Successfully applied: {success_count}/{len(self.settings_commands)} settings"
        )

        if failed_commands:
            print(f"  ✗ Failed commands: {len(failed_commands)}")
            for cmd, desc, error in failed_commands[:5]:
                print(f"     - {desc}: {error}")

        return {
            "serial": serial,
            "model": device_info.get("model"),
            "success_count": success_count,
            "total_commands": len(self.settings_commands),
            "failed_commands": failed_commands,
        }

    def configure_all_devices_parallel(self, devices):
        if not devices:
            print("No devices to configure")
            return []

        print(f"\n🚀 Starting parallel configuration for {len(devices)} device(s)...")
        print("=" * 60)

        with ThreadPoolExecutor(max_workers=len(devices)) as executor:
            futures = {}
            for serial, device_info in devices.items():
                future = executor.submit(self.configure_device, serial, device_info)
                futures[future] = serial

            results = []
            for future in as_completed(futures):
                serial = futures[future]
                try:
                    result = future.result(timeout=120)
                    results.append(result)
                except Exception as e:
                    print(f"❌ Error configuring {serial}: {str(e)}")
                    results.append(
                        {
                            "serial": serial,
                            "error": str(e),
                            "success_count": 0,
                            "total_commands": len(self.settings_commands),
                        }
                    )

        return results

    def print_final_summary(self, results):
        print("\n" + "=" * 60)
        print("📈 CONFIGURATION COMPLETE - FINAL SUMMARY")
        print("=" * 60)

        for result in results:
            serial = result.get("serial")
            model = result.get("model", "Unknown")
            success = result.get("success_count", 0)
            total = result.get("total_commands", 0)

            if "error" in result:
                print(f"\n❌ {serial} ({model}): ERROR - {result['error']}")
            else:
                percentage = (success / total * 100) if total > 0 else 0
                status = "✅" if percentage >= 80 else "⚠️" if percentage >= 50 else "❌"
                print(f"\n{status} {serial} ({model}):")
                print(f"   Applied: {success}/{total} settings ({percentage:.1f}%)")

                if result.get("failed_commands"):
                    print(f"   Failed settings:")
                    for cmd, desc, error in result["failed_commands"][:5]:
                        print(f"     - {desc}")

        print("\n" + "=" * 60)
        print("✔ Configuration process completed")
        print("=" * 60)

    def run(self):
        start_time = time.time()

        print("=" * 60)
        print("🚀 DEVICE CONFIGURATION UTILITY")
        print("=" * 60)
        print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Target devices: Samsung S10 series & OnePlus 6 series")
        print(f"Display size: Reset to default")
        print("=" * 60)

        devices = self.get_connected_devices()

        if not devices:
            print("\n⚠ No target devices found. Exiting.")
            return

        results = self.configure_all_devices_parallel(devices)

        self.print_final_summary(results)

        elapsed_time = time.time() - start_time
        print(f"\n⏱ Total execution time: {elapsed_time:.2f} seconds")

        print("\n💡 Note: Some settings may require a reboot to take full effect")
        print(
            "💡 You can verify settings using: adb shell settings list global/system/secure"
        )


if __name__ == "__main__":
    configurator = DeviceConfigurator()
    configurator.run()
