#!/usr/bin/env python3

import json
import os
import subprocess
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from cache_device_connection import DeviceConnectionClient


class AndroidSettingsFetcher:
    def __init__(self, output_dir="device_settings", max_workers=10):
        self.output_dir = output_dir
        self.max_workers = max_workers
        self.client = DeviceConnectionClient(auto_start_service=True)
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.ensure_output_dir()

        self.settings_categories = {
            "system": "system settings (UI preferences, sounds, display)",
            "secure": "secure settings (security, privacy, device admin)",
            "global": "global settings (system-wide configuration)",
        }

    def ensure_output_dir(self):

        os.makedirs(self.output_dir, exist_ok=True)
        print(f"Output directory: {os.path.abspath(self.output_dir)}")

    def execute_adb_command(self, serial, command, timeout=15):

        try:
            full_command = ["adb", "-s", serial, "shell", command]
            result = subprocess.run(
                full_command, capture_output=True, text=True, timeout=timeout
            )

            if result.returncode == 0:
                return {"status": "success", "data": result.stdout}
            else:
                return {
                    "status": "error",
                    "message": f"ADB command failed: {result.stderr or 'Unknown error'}",
                }

        except subprocess.TimeoutExpired:
            return {"status": "error", "message": "Command timeout"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def fetch_device_settings(self, serial, device_info):

        print(
            f"Fetching settings from {serial} ({device_info.get('model', 'Unknown')})"
        )

        device_settings = {
            "device_serial": serial,
            "device_model": device_info.get("model", "Unknown"),
            "fetch_timestamp": datetime.now().isoformat(),
            "fetch_time_unix": time.time(),
            "settings": {},
        }

        for category in self.settings_categories.keys():
            print(f"  Fetching {category} settings...")

            try:

                result = self.execute_adb_command(
                    serial, f"settings list {category}", timeout=15
                )

                if result.get("status") == "success":
                    raw_output = result.get("data", "")
                    parsed_settings = self.parse_settings_output(raw_output)
                    device_settings["settings"][category] = {
                        "raw_output": raw_output.strip(),
                        "parsed_count": len(parsed_settings),
                        "settings": parsed_settings,
                    }
                    print(f"    Success: {category}: {len(parsed_settings)} settings")
                else:
                    print(
                        f"    Failed: {category} settings: {result.get('message', 'Unknown error')}"
                    )
                    device_settings["settings"][category] = {
                        "error": result.get("message", "Unknown error"),
                        "raw_output": "",
                        "parsed_count": 0,
                        "settings": {},
                    }

            except Exception as e:
                print(f"    Exception: {category} settings: {str(e)}")
                device_settings["settings"][category] = {
                    "error": str(e),
                    "raw_output": "",
                    "parsed_count": 0,
                    "settings": {},
                }

        return serial, device_settings

    def parse_settings_output(self, raw_output):

        settings_dict = {}

        if not raw_output or not raw_output.strip():
            return settings_dict

        lines = raw_output.strip().split("\n")
        for line in lines:
            line = line.strip()
            if "=" in line:
                try:
                    key, value = line.split("=", 1)
                    settings_dict[key.strip()] = value.strip()
                except ValueError:

                    settings_dict[line] = ""
            elif line:
                settings_dict[line] = ""

        return settings_dict

    def save_device_settings(self, serial, device_settings, device_model):

        try:

            clean_model = device_model.replace(" ", "_").replace("/", "_")
            device_dir = os.path.join(self.output_dir, f"{clean_model}_{serial}")
            os.makedirs(device_dir, exist_ok=True)

            complete_file = os.path.join(device_dir, "all_settings.json")
            with open(complete_file, "w", encoding="utf-8") as f:
                json.dump(device_settings, f, indent=2, ensure_ascii=False)

            for category, data in device_settings["settings"].items():
                if data.get("settings"):
                    category_file = os.path.join(
                        device_dir, f"{category}_settings.json"
                    )
                    with open(category_file, "w", encoding="utf-8") as f:
                        json.dump(
                            {
                                "device_serial": serial,
                                "device_model": device_model,
                                "category": category,
                                "description": self.settings_categories.get(
                                    category, ""
                                ),
                                "fetch_timestamp": device_settings["fetch_timestamp"],
                                "settings_count": len(data["settings"]),
                                "settings": data["settings"],
                            },
                            f,
                            indent=2,
                            ensure_ascii=False,
                        )

                raw_file = os.path.join(device_dir, f"{category}_raw.txt")
                with open(raw_file, "w", encoding="utf-8") as f:
                    f.write(data.get("raw_output", ""))

            print(f"  Settings saved to: {device_dir}")
            return device_dir

        except Exception as e:
            print(f"  Failed to save settings for {serial}: {str(e)}")
            return None

    def fetch_all_devices_settings(self):

        print("Discovering connected devices...")

        result = self.client.discover_devices()
        if result.get("status") != "success":
            print(
                f"Failed to discover devices: {result.get('message', 'Unknown error')}"
            )
            return {}

        devices = result.get("data", {})
        if not devices:
            print(
                "No devices found. Make sure devices are connected and ADB debugging is enabled."
            )
            return {}

        print(f"Found {len(devices)} device(s):")
        for serial, info in devices.items():
            print(
                f"  • {serial}: {info.get('model', 'Unknown')} (connected: {info.get('connected_at', 'Unknown')})"
            )

        print(f"\nStarting parallel settings fetch from {len(devices)} devices...")
        print(
            "Using direct ADB commands to avoid service shell compatibility issues..."
        )

        futures = {}
        for serial, device_info in devices.items():
            future = self.executor.submit(
                self.fetch_device_settings, serial, device_info
            )
            futures[future] = serial

        all_settings = {}
        completed = 0

        for future in as_completed(futures):
            serial = futures[future]
            completed += 1

            try:
                serial_result, device_settings = future.result(timeout=120)
                all_settings[serial_result] = device_settings

                device_model = device_settings.get("device_model", "Unknown")
                saved_dir = self.save_device_settings(
                    serial_result, device_settings, device_model
                )

                if saved_dir:
                    print(f"Completed {completed}/{len(devices)}: {serial}")
                else:
                    print(
                        f"Fetched but failed to save {completed}/{len(devices)}: {serial}"
                    )

            except Exception as e:
                print(
                    f"Error processing {completed}/{len(devices)} - {serial}: {str(e)}"
                )
                traceback.print_exc()

        return all_settings

    def generate_summary_report(self, all_settings):

        if not all_settings:
            print("No settings data to summarize")
            return

        print(f"\nSettings Fetch Summary Report")
        print("=" * 60)

        summary_data = {
            "fetch_session": {
                "timestamp": datetime.now().isoformat(),
                "total_devices": len(all_settings),
                "successful_devices": len(
                    [d for d in all_settings.values() if d.get("settings")]
                ),
                "method": "Direct ADB commands",
            },
            "devices": {},
        }

        total_settings = 0

        for serial, device_data in all_settings.items():
            device_model = device_data.get("device_model", "Unknown")
            settings_data = device_data.get("settings", {})

            device_summary = {"model": device_model, "categories": {}}

            device_total = 0
            print(f"\n{serial} ({device_model})")

            for category, data in settings_data.items():
                count = data.get("parsed_count", 0)
                device_total += count
                device_summary["categories"][category] = {
                    "settings_count": count,
                    "has_error": "error" in data,
                }

                status = "Failed" if "error" in data else "Success"
                print(f"  {status}: {category}: {count} settings")

            summary_data["devices"][serial] = device_summary
            total_settings += device_total
            print(f"  Device Total: {device_total} settings")

        summary_data["total_settings_across_all_devices"] = total_settings

        summary_file = os.path.join(self.output_dir, "fetch_summary.json")
        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump(summary_data, f, indent=2, ensure_ascii=False)

        print(f"\nOverall Summary:")
        print(f"  • Total Devices: {len(all_settings)}")
        print(f"  • Total Settings: {total_settings}")
        print(f"  • Summary saved to: {summary_file}")

    def run(self):

        try:
            print("=" * 60)
            print(" Android Settings Fetcher - Fixed Version")
            print("=" * 60)
            print()

            try:
                subprocess.run(["adb", "version"], capture_output=True, check=True)
                print("ADB is available and ready")
            except (subprocess.CalledProcessError, FileNotFoundError):
                print("ERROR: ADB not found. Please install Android SDK platform-tools")
                return

            all_settings = self.fetch_all_devices_settings()

            if all_settings:

                self.generate_summary_report(all_settings)

                print(f"\nSettings fetch completed successfully!")
                print(f"All files saved to: {os.path.abspath(self.output_dir)}")

            else:
                print("\nNo settings were successfully fetched")

        except KeyboardInterrupt:
            print("\n\nProcess interrupted by user")
        except Exception as e:
            print(f"\nFatal error: {str(e)}")
            traceback.print_exc()
        finally:
            self.executor.shutdown(wait=False)

    def __del__(self):

        if hasattr(self, "executor"):
            self.executor.shutdown(wait=False)


if __name__ == "__main__":
    fetcher = AndroidSettingsFetcher(max_workers=10)
    fetcher.run()
