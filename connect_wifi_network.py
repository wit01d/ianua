import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from cache_device_connection import DeviceConnectionClient
from fetch_ui_service import FetchViewService


class WiFiToggleAutomation:
    def __init__(self, max_workers=10):
        self.client = DeviceConnectionClient(auto_start_service=True)
        self.fetch_service = FetchViewService()
        self.devices = self.fetch_service.devices
        self.executor = ThreadPoolExecutor(max_workers=max_workers)

    def get_device_model(self, serial):
        info_result = self.client.get_device_info(serial)
        if info_result.get("status") == "success":
            device_info = info_result.get("data", {})
            return device_info.get("productName", "").lower()
        return ""

    def open_wifi_settings(self, serial):
        print(f"[{serial}] Opening WiFi settings...")

        result = self.client.execute_action(
            serial, "shell", command="am start -a android.settings.WIFI_SETTINGS"
        )

        if result.get("status") != "success":
            print(f"[{serial}] Trying alternative method...")
            result = self.client.execute_action(
                serial,
                "shell",
                command="am start -a android.intent.action.MAIN -n com.android.settings/.wifi.WifiSettings",
            )

        return result.get("status") == "success"

    def find_element_by_text(self, elements, text_to_find):
        text_lower = text_to_find.lower()

        for elem in elements:
            elem_text = elem.get("text", "").lower()
            elem_content = elem.get("content_desc", "").lower()

            if text_lower in elem_text or text_lower in elem_content:
                return elem

        return None

    def find_gear_icon_near_element(self, elements, target_element):
        target_y = target_element["center_y"]

        for elem in elements:
            elem_resource = elem.get("resource_id", "")

            if elem_resource == "com.android.settings:id/wifi_details":
                y_distance = abs(elem["center_y"] - target_y)

                if y_distance < 100:
                    print(
                        f"Found wifi_details gear icon at ({elem['center_x']}, {elem['center_y']})"
                    )
                    return elem

        return None

    def is_kreativplaza_connected(self, elements):
        kreativplaza_elem = None
        connected_elem = None

        for i, elem in enumerate(elements):
            elem_text = elem.get("text", "").lower()
            elem_content = elem.get("content_desc", "").lower()

            if "kreativplaza" in elem_text or "kreativplaza" in elem_content:
                kreativplaza_elem = elem

                for j in range(max(0, i - 5), min(len(elements), i + 5)):
                    nearby = elements[j]
                    nearby_text = nearby.get("text", "").lower()
                    nearby_content = nearby.get("content_desc", "").lower()

                    if "connected" in nearby_text or "connected" in nearby_content:
                        if abs(nearby["center_y"] - elem["center_y"]) < 100:
                            connected_elem = nearby
                            print(f"Found 'kreativplaza' with 'connected' status")
                            return kreativplaza_elem, True

        if kreativplaza_elem:
            print(f"Found 'kreativplaza' but not connected")
            return kreativplaza_elem, False

        return None, False

    def click_kreativplaza_or_add_network(self, serial, elements):
        kreativplaza_elem, is_connected = self.is_kreativplaza_connected(elements)

        if kreativplaza_elem and is_connected:
            gear_elem = self.find_gear_icon_near_element(elements, kreativplaza_elem)

            if gear_elem:
                print(f"[{serial}] Clicking gear icon for connected kreativplaza...")
                click_result = self.client.execute_action(
                    serial,
                    "click",
                    x=gear_elem["center_x"],
                    y=gear_elem["center_y"],
                )

                if click_result.get("status") == "success":
                    print(f"[{serial}] Successfully clicked gear icon for kreativplaza")
                    return True
                else:
                    print(f"[{serial}] Failed to click gear icon")
                    return False
            else:
                print(f"[{serial}] No gear icon found near connected kreativplaza")
                return False

        elif kreativplaza_elem and not is_connected:
            print(
                f"[{serial}] Found 'kreativplaza' (not connected) at ({kreativplaza_elem['center_x']}, {kreativplaza_elem['center_y']})"
            )
            click_result = self.client.execute_action(
                serial,
                "click",
                x=kreativplaza_elem["center_x"],
                y=kreativplaza_elem["center_y"],
            )

            if click_result.get("status") == "success":
                print(f"[{serial}] Successfully clicked on kreativplaza to connect")
                return True
            else:
                print(f"[{serial}] Failed to click kreativplaza")
                return False

        add_network_elem = self.find_element_by_text(elements, "add network")

        if add_network_elem:
            print(
                f"[{serial}] Found 'add network' at ({add_network_elem['center_x']}, {add_network_elem['center_y']})"
            )
            click_result = self.client.execute_action(
                serial,
                "click",
                x=add_network_elem["center_x"],
                y=add_network_elem["center_y"],
            )

            if click_result.get("status") == "success":
                print(f"[{serial}] Successfully clicked on 'add network'")
                return True
            else:
                print(f"[{serial}] Failed to click 'add network'")
                return False

        print(f"[{serial}] Neither 'kreativplaza' nor 'add network' found")
        return False

    def find_wifi_toggle_samsung(self, elements):
        wifi_toggle = None

        for i, elem in enumerate(elements):
            text = elem.get("text", "").lower()
            if text in ["off", "on"]:
                for j in range(max(0, i - 5), min(len(elements), i + 5)):
                    nearby = elements[j]
                    if (
                        "switch" in nearby.get("class", "").lower()
                        or "toggle" in nearby.get("class", "").lower()
                        or "checkbox" in nearby.get("class", "").lower()
                        or nearby.get("checkable", False)
                    ):
                        if abs(nearby["center_y"] - elem["center_y"]) < 50:
                            wifi_toggle = nearby
                            break

                if not wifi_toggle:
                    for j in range(max(0, i - 10), min(len(elements), i + 10)):
                        nearby = elements[j]
                        nearby_text = nearby.get("text", "").lower()
                        if "wi-fi" in nearby_text or "wifi" in nearby_text:
                            if abs(nearby["center_y"] - elem["center_y"]) < 100:
                                wifi_toggle = elem
                                break

        return wifi_toggle

    def find_wifi_toggle_oneplus(self, elements):
        wifi_toggle = None

        for i, elem in enumerate(elements):
            text = elem.get("text", "").lower()
            content = elem.get("content_desc", "").lower()

            if (
                "wi-fi" in text
                or "wifi" in text
                or "wi-fi" in content
                or "wifi" in content
            ):
                for j in range(max(0, i - 10), min(len(elements), i + 10)):
                    nearby = elements[j]
                    if (
                        "switch" in nearby.get("class", "").lower()
                        or "toggle" in nearby.get("class", "").lower()
                        or "checkbox" in nearby.get("class", "").lower()
                        or nearby.get("checkable", False)
                    ):
                        if abs(nearby["center_y"] - elem["center_y"]) < 50:
                            wifi_toggle = nearby
                            break

        return wifi_toggle

    def find_wifi_toggle_generic(self, elements):
        wifi_toggle = None

        for elem in elements:
            resource_id = elem.get("resource_id", "").lower()
            content = elem.get("content_desc", "").lower()

            if (
                "wifi" in resource_id
                or "wi_fi" in resource_id
                or "switch_widget" in resource_id
                or "switch_bar" in resource_id
            ):
                if (
                    elem.get("checkable", False)
                    or "switch" in elem.get("class", "").lower()
                ):
                    wifi_toggle = elem
                    break

            if ("wifi" in content or "wi-fi" in content) and "toggle" in content:
                wifi_toggle = elem
                break

        return wifi_toggle

    def process_single_device(self, serial, info):
        start_time = time.time()
        result = {
            "serial": serial,
            "model": info.get("model", "Unknown"),
            "success": False,
            "error": None,
            "duration": 0,
        }

        try:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting {serial}")

            if not self.open_wifi_settings(serial):
                result["error"] = "Failed to open WiFi settings"
                return result

            time.sleep(2)

            hierarchy_result = self.client.dump_hierarchy(
                serial, compressed=False, pretty=False
            )
            if hierarchy_result.get("status") != "success":
                result["error"] = "Failed to dump hierarchy"
                return result

            hierarchy_xml = hierarchy_result.get("data", "")
            if not hierarchy_xml:
                result["error"] = "Empty hierarchy"
                return result

            elements = self.fetch_service.parse_hierarchy_simple(hierarchy_xml)
            print(f"[{serial}] Parsed {len(elements)} UI elements")

            self.click_kreativplaza_or_add_network(serial, elements)

            time.sleep(2)

            hierarchy_result = self.client.dump_hierarchy(
                serial, compressed=False, pretty=False
            )
            if hierarchy_result.get("status") == "success":
                hierarchy_xml = hierarchy_result.get("data", "")
                elements = self.fetch_service.parse_hierarchy_simple(hierarchy_xml)

            device_model = self.get_device_model(serial)
            print(f"[{serial}] Device model: {device_model}")

            wifi_toggle = None

            if "sm-" in device_model or "samsung" in device_model:
                print(f"[{serial}] Using Samsung detection...")
                wifi_toggle = self.find_wifi_toggle_samsung(elements)
            elif "oneplus" in device_model or "op" in device_model:
                print(f"[{serial}] Using OnePlus detection...")
                wifi_toggle = self.find_wifi_toggle_oneplus(elements)

            if not wifi_toggle:
                print(f"[{serial}] Using generic detection...")
                wifi_toggle = self.find_wifi_toggle_generic(elements)

            if wifi_toggle:
                if wifi_toggle.get("checked", False):
                    print(f"[{serial}] WiFi is already ON")
                    result["success"] = True
                else:
                    print(f"[{serial}] Clicking WiFi toggle...")
                    click_result = self.client.execute_action(
                        serial,
                        "click",
                        x=wifi_toggle["center_x"],
                        y=wifi_toggle["center_y"],
                    )

                    if click_result.get("status") == "success":
                        print(f"[{serial}] ✓ WiFi toggle clicked")
                        result["success"] = True

                        time.sleep(2)

                        verify_result = self.client.dump_hierarchy(
                            serial, compressed=False, pretty=False
                        )
                        if verify_result.get("status") == "success":
                            verify_elements = self.fetch_service.parse_hierarchy_simple(
                                verify_result.get("data", "")
                            )
                            for elem in verify_elements:
                                if elem.get("resource_id", "") == wifi_toggle.get(
                                    "resource_id", ""
                                ) and elem.get("bounds", "") == wifi_toggle.get(
                                    "bounds", ""
                                ):
                                    if elem.get("checked", False):
                                        print(f"[{serial}] ✓ WiFi verified as ON")
                                    else:
                                        print(f"[{serial}] ⚠ WiFi state unchanged")
                                    break
                    else:
                        result["error"] = (
                            f"Failed to click toggle: {click_result.get('message', 'Unknown')}"
                        )
            else:
                result["error"] = "Could not find WiFi toggle"

        except Exception as e:
            result["error"] = str(e)
            print(f"[{serial}] Error: {e}")

        result["duration"] = time.time() - start_time
        print(f"[{serial}] Completed in {result['duration']:.2f}s")
        return result

    def toggle_wifi_all_devices_parallel(self):
        if not self.devices:
            print("No devices connected")
            return []

        print(f"\n{'=' * 60}")
        print(f"Processing {len(self.devices)} device(s) in parallel")
        print(f"Start time: {datetime.now().strftime('%H:%M:%S')}")
        print(f"{'=' * 60}\n")

        futures = {}
        for serial, info in self.devices.items():
            future = self.executor.submit(self.process_single_device, serial, info)
            futures[future] = serial

        results = []
        completed = 0

        for future in as_completed(futures):
            completed += 1
            serial = futures[future]
            try:
                result = future.result(timeout=30)
                results.append(result)

                status = (
                    "✓ SUCCESS" if result["success"] else f"✗ FAILED: {result['error']}"
                )
                print(f"\n[{completed}/{len(self.devices)}] {serial}: {status}")

            except Exception as e:
                print(f"\n[{completed}/{len(self.devices)}] {serial}: ✗ ERROR: {e}")
                results.append(
                    {"serial": serial, "success": False, "error": str(e), "duration": 0}
                )

        return results

    def run_test(self):
        print("\n" + "=" * 60)
        print("WiFi Toggle Automation - Parallel Processing")
        print("=" * 60)
        print(f"Found {len(self.devices)} device(s)")

        for serial, info in self.devices.items():
            print(f"  • {serial}: {info.get('model', 'Unknown')}")

        if self.devices:
            start_time = time.time()
            results = self.toggle_wifi_all_devices_parallel()
            total_time = time.time() - start_time

            print(f"\n{'=' * 60}")
            print("SUMMARY")
            print(f"{'=' * 60}")

            successful = sum(1 for r in results if r["success"])
            failed = len(results) - successful

            print(f"Total devices: {len(results)}")
            print(f"Successful: {successful}")
            print(f"Failed: {failed}")
            print(f"Total time: {total_time:.2f}s")
            print(f"Average time per device: {total_time/len(results):.2f}s")

            if failed > 0:
                print(f"\nFailed devices:")
                for r in results:
                    if not r["success"]:
                        print(f"  • {r['serial']}: {r['error']}")
        else:
            print("\nNo devices found. Please connect devices via USB/ADB")

    def __del__(self):
        if hasattr(self, "executor"):
            self.executor.shutdown(wait=False)


if __name__ == "__main__":
    automation = WiFiToggleAutomation(max_workers=10)
    automation.run_test()
