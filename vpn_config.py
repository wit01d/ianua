import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from cache_device_connection import DeviceConnectionClient
from fetch_ui_service import FetchViewService


class VPNAutoAccepter:
    def __init__(self):
        self.client = DeviceConnectionClient(auto_start_service=True)
        self.fetch_service = FetchViewService()
        self.devices = self._get_devices()

    def _get_devices(self):
        result = self.client.discover_devices()
        if result.get("status") == "success":
            return result.get("data", {})
        return {}

    def find_ok_button(self, serial):
        try:
            hierarchy_result = self.client.dump_hierarchy(
                serial, compressed=False, pretty=False
            )

            if hierarchy_result.get("status") != "success":
                return None

            hierarchy_xml = hierarchy_result.get("data", "")
            if not hierarchy_xml:
                return None

            elements = self.fetch_service.parse_hierarchy_simple(hierarchy_xml)

            for elem in elements:
                text = elem.get("text", "").strip().upper()
                content_desc = elem.get("content_desc", "").strip().upper()
                resource_id = elem.get("resource_id", "")

                if text == "OK" or content_desc == "OK":
                    if elem.get("clickable", False) and elem.get("enabled", False):
                        return {
                            "x": elem.get("center_x"),
                            "y": elem.get("center_y"),
                            "bounds": elem.get("bounds"),
                            "text": elem.get("text"),
                            "resource_id": resource_id,
                        }

                if (
                    "android:id/button1" in resource_id
                    or "positive" in resource_id.lower()
                ):
                    if elem.get("clickable", False) and elem.get("enabled", False):
                        return {
                            "x": elem.get("center_x"),
                            "y": elem.get("center_y"),
                            "bounds": elem.get("bounds"),
                            "text": elem.get("text"),
                            "resource_id": resource_id,
                        }

            for elem in elements:
                if elem.get("class", "") == "android.widget.Button":
                    if elem.get("clickable", False) and elem.get("enabled", False):
                        x_pos = elem.get("x1", 0)
                        if x_pos > 500:
                            return {
                                "x": elem.get("center_x"),
                                "y": elem.get("center_y"),
                                "bounds": elem.get("bounds"),
                                "text": elem.get("text"),
                                "resource_id": elem.get("resource_id"),
                            }

            return None

        except Exception as e:
            print(f"[{serial}] Error finding OK button: {e}")
            return None

    def check_for_vpn_dialog(self, serial):
        try:
            hierarchy_result = self.client.dump_hierarchy(
                serial, compressed=False, pretty=False
            )

            if hierarchy_result.get("status") != "success":
                return False

            hierarchy_xml = hierarchy_result.get("data", "")
            if not hierarchy_xml:
                return False

            vpn_keywords = [
                "connection request",
                "vpn connection",
                "gnirehtet wants to set up",
                "gnirehtet",
                "monitor network traffic",
                "trust the source",
            ]

            hierarchy_lower = hierarchy_xml.lower()
            for keyword in vpn_keywords:
                if keyword in hierarchy_lower:
                    return True

            elements = self.fetch_service.parse_hierarchy_simple(hierarchy_xml)
            for elem in elements:
                text = elem.get("text", "").lower()
                content_desc = elem.get("content_desc", "").lower()

                for keyword in vpn_keywords:
                    if keyword in text or keyword in content_desc:
                        return True

            return False

        except Exception as e:
            print(f"[{serial}] Error checking for VPN dialog: {e}")
            return False

    def click_ok_button(self, serial, button_info):
        try:
            device_info = self.devices.get(serial, {})
            model = device_info.get("model", "Unknown")

            x = button_info["x"]
            y = button_info["y"]

            print(f"[{serial}] Clicking OK at ({x}, {y}) on {model}...")

            result = subprocess.run(
                ["adb", "-s", serial, "shell", f"input tap {x} {y}"],
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode == 0:
                print(f"[{serial}] ✓ Clicked OK button successfully on {model}")
                return True
            else:
                print(f"[{serial}] ❌ Failed to click OK: {result.stderr}")
                return False

        except Exception as e:
            print(f"[{serial}] ❌ Error clicking OK: {e}")
            return False

    def accept_vpn_on_device(self, serial):
        try:
            device_info = self.devices.get(serial, {})
            model = device_info.get("model", "Unknown")

            print(f"[{serial}] Checking for VPN dialog on {model}...")

            if not self.check_for_vpn_dialog(serial):
                print(f"[{serial}] No VPN dialog found on {model}")
                return False

            print(f"[{serial}] VPN dialog detected on {model}")

            button_info = self.find_ok_button(serial)

            if not button_info:
                print(f"[{serial}] ❌ Could not find OK button on {model}")
                return False

            print(
                f"[{serial}] Found OK button at ({button_info['x']}, {button_info['y']})"
            )

            return self.click_ok_button(serial, button_info)

        except Exception as e:
            print(f"[{serial}] ❌ Error accepting VPN: {e}")
            return False

    def accept_all_vpn_requests(self, max_retries=3):
        print(f"\n{'='*60}")
        print(f"Accepting VPN requests on {len(self.devices)} devices")
        print(f"{'='*60}\n")

        for retry in range(max_retries):
            if retry > 0:
                print(f"\n--- Retry {retry}/{max_retries - 1} ---\n")
                time.sleep(2)

            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = {
                    executor.submit(self.accept_vpn_on_device, serial): serial
                    for serial in self.devices
                }

                results = {}
                for future in as_completed(futures):
                    serial = futures[future]
                    try:
                        results[serial] = future.result()
                    except Exception as e:
                        print(f"[{serial}] ❌ Exception: {e}")
                        results[serial] = False

            successful = sum(1 for success in results.values() if success)

            if successful == len(self.devices):
                print(f"\n✅ All {successful} VPN requests accepted successfully!")
                return results
            elif successful > 0:
                print(f"\n⚠ Accepted {successful}/{len(self.devices)} VPN requests")

            failed_devices = [s for s, success in results.items() if not success]
            if failed_devices and retry < max_retries - 1:
                print(f"Retrying {len(failed_devices)} failed devices...")
                self.devices = {s: self.devices[s] for s in failed_devices}

        print(f"\n{'='*60}")
        print(f"Final result: {successful}/{len(self.devices)} VPN requests accepted")
        print(f"{'='*60}\n")

        return results

    def monitor_and_accept(self, check_interval=5, duration=60):
        print(f"\n📡 Monitoring for VPN dialogs for {duration} seconds...")
        print(f"Checking every {check_interval} seconds\n")

        start_time = time.time()
        accepted_devices = set()

        while time.time() - start_time < duration:
            pending_devices = {
                s: info for s, info in self.devices.items() if s not in accepted_devices
            }

            if not pending_devices:
                print("\n✅ All devices have accepted VPN connections!")
                break

            for serial in pending_devices:
                if self.check_for_vpn_dialog(serial):
                    print(
                        f"\n[{datetime.now().strftime('%H:%M:%S')}] VPN dialog appeared on {serial}"
                    )
                    if self.accept_vpn_on_device(serial):
                        accepted_devices.add(serial)

            remaining = len(self.devices) - len(accepted_devices)
            if remaining > 0:
                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] Still waiting for {remaining} device(s)..."
                )

            time.sleep(check_interval)

        print(f"\n📊 Final Status:")
        print(f"  ✓ Accepted: {len(accepted_devices)}/{len(self.devices)}")
        if accepted_devices:
            print(f"  Devices: {', '.join(accepted_devices)}")


def main():
    print("╔" + "═" * 58 + "╗")
    print("║" + " VPN Connection Auto-Accepter".center(58) + "║")
    print("╚" + "═" * 58 + "╝")

    accepter = VPNAutoAccepter()

    if not accepter.devices:
        print("\n❌ No devices found. Please connect devices and try again.")
        return

    print(f"\n✓ Found {len(accepter.devices)} connected device(s)")
    for serial, device_info in accepter.devices.items():
        print(f"  • {serial}: {device_info.get('model', 'Unknown')}")

    accepter.monitor_and_accept(check_interval=3, duration=60)

    print("\n✓ Process complete!")


if __name__ == "__main__":
    main()
