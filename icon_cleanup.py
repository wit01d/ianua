import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import uiautomator2 as u2

from cache_device_connection import DeviceConnectionClient
from notification_dismissal import DevicePermissionHandler


class IconCleanupHandler:
    def __init__(self):
        self.client = DeviceConnectionClient(auto_start_service=True)
        self.monitor = DevicePermissionHandler()
        self.batch_size = 5
        self.remove_timeout = 10

    def get_display_dimensions(self, device):
        try:
            info = device.info
            width = info.get("displayWidth", 1080)
            height = info.get("displayHeight", 1920)
            return width, height
        except Exception as e:
            print(f"Error getting display dimensions: {e}")
            return 1080, 1920

    def calculate_drag_duration(self, width, height):
        base_size = 1920
        size_ratio = max(width, height) / base_size
        base_duration = 1.0
        return base_duration / (9 * size_ratio)

    def go_to_home_screen(self, serial):
        try:
            device = self.monitor.device_connections.get(serial)
            if device:
                device.press("home")
                time.sleep(0.5)
                text_elements = self.monitor.get_text_elements_from_device(
                    device, serial
                )
                is_on_home = any(
                    "home screen" in element["text"].lower()
                    or "home" in element["text"].lower()
                    or "launcher" in element["text"].lower()
                    for element in text_elements
                )
                if not is_on_home:
                    device.press("home")
                    time.sleep(0.5)
                return True
            return False
        except Exception as e:
            print(f"[{serial}] Error navigating to home screen: {e}")
            return False

    def find_icons(self, serial):
        try:
            device = self.monitor.device_connections.get(serial)
            if not device:
                return []

            width, height = self.get_display_dimensions(device)
            xml = device.dump_hierarchy()

            import xml.etree.ElementTree as ET

            root = ET.fromstring(xml)
            icons = []

            for elem in root.iter():
                if (
                    elem.get("class", "").endswith("IconView")
                    or elem.get("resource-id", "").endswith("icon")
                    or elem.get("content-desc", "")
                    and elem.get("clickable") == "true"
                ):
                    bounds = elem.get("bounds", "")
                    if bounds:
                        import re

                        match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
                        if match:
                            x1, y1, x2, y2 = map(int, match.groups())
                            center_x = (x1 + x2) // 2
                            center_y = (y1 + y2) // 2
                            if y1 > height * 0.1 and y2 < height * 0.9:
                                icons.append(
                                    {
                                        "position": (center_x, center_y),
                                        "bounds": (x1, y1, x2, y2),
                                        "text": elem.get("text", ""),
                                        "desc": elem.get("content-desc", ""),
                                    }
                                )

            print(f"[{serial}] Found {len(icons)} potential icons on home screen")
            return icons
        except Exception as e:
            print(f"[{serial}] Error finding icons: {e}")
            return []

    def get_device_specific_remove_position(self, serial):
        try:
            device = self.monitor.device_connections.get(serial)
            if not device:
                return None

            device_info = device.info
            model = device_info.get("productName", "").lower()
            brand = device_info.get("brand", "").lower()

            if "oneplus" in model and "6" in model:
                return (540, 263)
            elif "samsung" in brand or "samsung" in model:
                return (541, 350)
            else:
                width, height = self.get_display_dimensions(device)
                return (width // 2, height // 10)

        except Exception as e:
            print(f"[{serial}] Error getting device-specific position: {e}")
            width, height = self.get_display_dimensions(device)
            return (width // 2, height // 10)

    def remove_icon(self, serial, icon, remove_position):
        try:
            device = self.monitor.device_connections.get(serial)
            if not device:
                return False

            width, height = self.get_display_dimensions(device)
            drag_duration = self.calculate_drag_duration(width, height)

            x, y = icon["position"]
            remove_x, remove_y = remove_position

            print(
                f"[{serial}] Dragging icon from ({x}, {y}) to remove area ({remove_x}, {remove_y}) - duration: {drag_duration:.2f}s"
            )

            device.drag(x, y, remove_x, remove_y, duration=drag_duration)
            time.sleep(0.2)

            confirm_elements = self.monitor.get_text_elements_from_device(
                device, serial
            )
            for confirm_elem in confirm_elements:
                if confirm_elem["text"].lower() in ["ok", "yes", "remove", "confirm"]:
                    device.click(
                        confirm_elem["position"][0], confirm_elem["position"][1]
                    )
                    time.sleep(0.2)
                    break

            return True

        except Exception as e:
            print(f"[{serial}] Error removing icon: {e}")
            return False

    def clean_icons_on_device(self, serial):
        try:
            print(f"[{serial}] Starting icon cleanup...")

            if not self.go_to_home_screen(serial):
                print(f"[{serial}] Failed to navigate to home screen")
                return {"removed": 0, "success": False}

            icons = self.find_icons(serial)
            if not icons:
                print(f"[{serial}] No icons found on home screen")
                return {"removed": 0, "success": True}

            remove_position = self.get_device_specific_remove_position(serial)

            device = self.monitor.device_connections.get(serial)
            device_info = device.info
            model = device_info.get("productName", "")
            brand = device_info.get("brand", "")

            print(
                f"[{serial}] Device: {brand} {model}, Remove position: {remove_position}"
            )

            removed_count = 0
            for icon in icons:
                if self.remove_icon(serial, icon, remove_position):
                    removed_count += 1
                    time.sleep(0.2)

            print(f"[{serial}] Removed {removed_count} of {len(icons)} icons")
            return {"removed": removed_count, "total": len(icons), "success": True}

        except Exception as e:
            print(f"[{serial}] Error cleaning icons: {e}")
            return {"removed": 0, "success": False, "error": str(e)}

    def clean_all_devices(self):
        result = self.client.discover_devices()
        if result.get("status") != "success":
            print("Failed to discover devices")
            return {}

        devices = result.get("data", {})
        if not devices:
            print("No devices found to clean")
            return {}

        print(f"\n{'='*60}")
        print(f"Starting icon cleanup on {len(devices)} device(s)")
        print(f"{'='*60}")

        results = {}
        device_list = list(devices.items())

        for i in range(0, len(device_list), self.batch_size):
            batch = device_list[i : i + self.batch_size]
            batch_num = i // self.batch_size + 1
            total_batches = (len(device_list) + self.batch_size - 1) // self.batch_size

            print(f"\n{'='*40}")
            print(
                f"Processing batch {batch_num}/{total_batches} ({len(batch)} devices)"
            )
            print(f"{'='*40}")

            with ThreadPoolExecutor(
                max_workers=min(self.batch_size, len(batch))
            ) as executor:
                futures = {
                    executor.submit(self.clean_icons_on_device, serial): serial
                    for serial, info in batch
                }

                batch_completed = 0
                for future in as_completed(futures):
                    serial = futures[future]
                    batch_completed += 1
                    total_completed = i + batch_completed

                    try:
                        result = future.result()
                        results[serial] = {
                            "removed": result.get("removed", 0),
                            "total": result.get("total", 0),
                            "success": result.get("success", False),
                            "model": devices[serial].get("model", "Unknown"),
                        }
                        status = "✓" if result.get("success") else "✗"
                        print(
                            f"\n[{total_completed}/{len(devices)}] {status} Device {serial} completed"
                        )
                    except Exception as e:
                        print(
                            f"\n[{total_completed}/{len(devices)}] ✗ Device {serial} error: {e}"
                        )
                        results[serial] = {
                            "removed": 0,
                            "success": False,
                            "error": str(e),
                            "model": devices[serial].get("model", "Unknown"),
                        }

            if i + self.batch_size < len(device_list):
                print(f"\nWaiting 5 seconds before next batch...")
                time.sleep(5)

        return results

    def print_summary(self, results):
        print(f"\n{'='*60}")
        print("Icon Cleanup Summary")
        print(f"{'='*60}")

        successful = sum(1 for r in results.values() if r["success"])
        failed = len(results) - successful
        total_removed = sum(r.get("removed", 0) for r in results.values())

        print(f"\nTotal devices: {len(results)}")
        print(f"✓ Successfully processed: {successful}")
        print(f"✗ Failed to process: {failed}")
        print(f"Icons removed: {total_removed}")

        if successful > 0:
            print(f"\nSuccessful Devices:")
            print(f"{'-'*40}")
            for serial, result in results.items():
                if result["success"]:
                    model = result["model"]
                    removed = result.get("removed", 0)
                    total = result.get("total", 0)
                    print(f"  {serial} ({model})")
                    print(f"    Removed {removed}/{total} icons")

        if failed > 0:
            print(f"\nFailed Devices:")
            print(f"{'-'*40}")
            for serial, result in results.items():
                if not result["success"]:
                    model = result["model"]
                    error = result.get("error", "Unknown error")
                    print(f"  {serial} ({model})")
                    print(f"    Error: {error}")

        print(f"\n{'='*60}")


def main():
    print(f"Icon Cleanup Tool")
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    cleaner = IconCleanupHandler()
    results = cleaner.clean_all_devices()
    cleaner.print_summary(results)

    print(f"\nCompleted at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
