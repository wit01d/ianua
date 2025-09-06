import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import uiautomator2 as u2

from fetch_ui_service import FetchViewService


class DevicePermissionHandler:
    def __init__(self):
        self.monitor = FetchViewService()
        self.device_connections = {}
        self.failed_connections = set()
        self.keepalive_interval = 5
        self._init_device_connections()
        self._start_keepalive_thread()

    def _init_device_connections(self):
        with ThreadPoolExecutor(
            max_workers=min(10, len(self.monitor.devices))
        ) as executor:
            futures = {
                executor.submit(self._connect_device, serial): serial
                for serial in self.monitor.devices
            }
            for future in as_completed(futures):
                serial = futures[future]
                try:
                    device = future.result(timeout=30)
                    if device:
                        self.device_connections[serial] = device
                except Exception as e:
                    print(f"Failed to connect to device {serial}: {e}")
                    self.failed_connections.add(serial)

    def _connect_device(self, serial):
        try:
            device = u2.connect(serial)
            device.implicitly_wait(0.1)
            device.settings["wait_timeout"] = 5.0
            return device
        except Exception as e:
            print(f"Connection failed for {serial}: {e}")
            return None

    def _start_keepalive_thread(self):
        def keepalive_worker():
            while True:
                time.sleep(self.keepalive_interval)
                self._send_keepalive_all_parallel()

        thread = threading.Thread(target=keepalive_worker, daemon=True)
        thread.start()

    def _send_keepalive_all_parallel(self):
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = []
            for serial, device in list(self.device_connections.items()):
                if device:
                    future = executor.submit(
                        self._send_single_keepalive, serial, device
                    )
                    futures.append(future)

            for future in as_completed(futures, timeout=1):
                try:
                    future.result()
                except:
                    pass

    def _send_single_keepalive(self, serial, device):
        try:
            device.shell("echo k", timeout=0.5)
        except:
            self.failed_connections.add(serial)

    def reconnect_devices_batch(self, serials):
        with ThreadPoolExecutor(max_workers=len(serials)) as executor:
            futures = {
                executor.submit(self.reconnect_device, serial): serial
                for serial in serials
            }
            results = {}
            for future in as_completed(futures, timeout=3):
                serial = futures[future]
                try:
                    results[serial] = future.result()
                except:
                    results[serial] = None
        return results

    def reconnect_device(self, serial):
        try:
            device = u2.connect(serial)
            device.implicitly_wait(0.1)
            device.settings["wait_timeout"] = 5.0
            self.device_connections[serial] = device
            self.failed_connections.discard(serial)
            return device
        except Exception as e:
            print(f"Failed to reconnect to device {serial}: {e}")
            self.failed_connections.add(serial)
            return None

    def get_text_elements_from_device(self, device, serial=None, allow_reconnect=True):
        text_elements = []
        max_retries = 2

        for retry in range(max_retries):
            try:
                xml = device.dump_hierarchy()
                import xml.etree.ElementTree as ET

                root = ET.fromstring(xml)

                for elem in root.iter():
                    text = elem.get("text", "")
                    if text:
                        bounds = elem.get("bounds", "")
                        clickable = elem.get("clickable", "false") == "true"

                        if bounds:
                            import re

                            match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
                            if match:
                                x1, y1, x2, y2 = map(int, match.groups())
                                x = (x1 + x2) // 2
                                y = (y1 + y2) // 2

                                text_elements.append(
                                    {
                                        "text": text,
                                        "position": (x, y),
                                        "clickable": clickable,
                                        "bounds": (x1, y1, x2, y2),
                                    }
                                )
                return text_elements

            except Exception as e:
                if retry == 0 and serial and allow_reconnect:
                    time.sleep(0.2)
                    continue
                if retry == max_retries - 1:
                    if serial and allow_reconnect:
                        print(
                            f"Persistent error getting UI hierarchy from {serial}, attempting reconnect..."
                        )
                        device = self.reconnect_device(serial)
                        if device:
                            try:
                                xml = device.dump_hierarchy()
                                import xml.etree.ElementTree as ET

                                root = ET.fromstring(xml)
                                for elem in root.iter():
                                    text = elem.get("text", "")
                                    if text:
                                        bounds = elem.get("bounds", "")
                                        clickable = (
                                            elem.get("clickable", "false") == "true"
                                        )
                                        if bounds:
                                            import re

                                            match = re.match(
                                                r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]",
                                                bounds,
                                            )
                                            if match:
                                                x1, y1, x2, y2 = map(
                                                    int, match.groups()
                                                )
                                                x = (x1 + x2) // 2
                                                y = (y1 + y2) // 2
                                                text_elements.append(
                                                    {
                                                        "text": text,
                                                        "position": (x, y),
                                                        "clickable": clickable,
                                                        "bounds": (x1, y1, x2, y2),
                                                    }
                                                )
                                return text_elements
                            except:
                                pass
                    print(f"Error getting UI hierarchy: {e}")

        return text_elements

    def find_allow_button(self, text_elements):
        for element in text_elements:
            if element["text"].lower() == "allow" and element["clickable"]:
                return element["position"]
        return None

    def check_and_dismiss_lock_screen_notification(self, serial):
        try:
            device = self.device_connections.get(serial)
            if not device:
                return False

            text_elements = self.get_text_elements_from_device(
                device, serial, allow_reconnect=False
            )

            lock_screen_element = None
            agree_button = None

            for element in text_elements:
                if (
                    "Rediscover your Lock Screen" in element["text"]
                    and "Access what You " in element["text"]
                ):
                    lock_screen_element = element

            if not lock_screen_element:
                return False

            for element in text_elements:
                if (
                    "Great!" in element["text"]
                    and "I agree" in element["text"]
                    and element["clickable"]
                ):
                    agree_button = element
                    break

            if agree_button:
                x, y = agree_button["position"]
                device.click(x, y)
                print(
                    f"Clicked 'Great! I agree' on lock screen notification on device {serial}"
                )
                return True
            else:
                print(
                    f"Found lock screen notification but no 'Great! I agree' button on device {serial}"
                )
                return False

        except Exception as e:
            print(f"Error checking lock screen notification on device {serial}: {e}")
            return False

    def dismiss_lock_screen_all_devices(self):
        dismissed = {}

        with ThreadPoolExecutor(max_workers=999) as executor:
            future_to_serial = {
                executor.submit(
                    self.check_and_dismiss_lock_screen_notification, serial
                ): serial
                for serial in self.device_connections
            }

            for future in as_completed(future_to_serial):
                serial = future_to_serial[future]
                try:
                    result = future.result()
                    dismissed[serial] = result
                except Exception as e:
                    print(f"Error processing device {serial}: {e}")
                    dismissed[serial] = False

        return dismissed

    def verify_click_success(self, device, serial):
        try:
            time.sleep(0.5)
            text_elements = self.get_text_elements_from_device(
                device, serial, allow_reconnect=False
            )

            has_permission_dialog = any(
                "allow access to phone data" in element["text"].lower()
                for element in text_elements
            )

            if not has_permission_dialog:
                print(
                    f"Permission dialog disappeared on {serial} - click was successful"
                )
                return True
            else:
                print(
                    f"Permission dialog still present on {serial} - click may have failed"
                )
                return False
        except Exception as e:
            print(f"Error verifying click on {serial}: {e}")
            return True

    def click_allow_on_device(self, serial):
        try:
            device = self.device_connections.get(serial)
            if not device:
                return {"clicked": False, "reason": "Device not found"}

            text_elements = self.get_text_elements_from_device(device, serial)

            has_permission_dialog = any(
                "allow access to phone data" in element["text"].lower()
                for element in text_elements
            )

            if not has_permission_dialog:
                return {"clicked": False, "reason": "No permission dialog found"}

            allow_position = self.find_allow_button(text_elements)

            if allow_position:
                x, y = allow_position
                try:
                    device.click(x, y)
                    print(f"Clicked Allow on device {serial} at coordinates ({x}, {y})")

                    if self.verify_click_success(device, serial):
                        return {
                            "clicked": True,
                            "coordinates": (x, y),
                            "verified_success": True,
                        }
                    else:
                        print(f"Click may have failed on {serial}, attempting retry...")
                        time.sleep(0.5)
                        device.click(x, y)
                        print(f"Retrying click on device {serial}")

                        if self.verify_click_success(device, serial):
                            return {
                                "clicked": True,
                                "coordinates": (x, y),
                                "verified_success": True,
                                "retry": True,
                            }
                        else:
                            return {
                                "clicked": True,
                                "coordinates": (x, y),
                                "verified_success": False,
                            }

                except Exception as click_error:
                    print(f"Click exception on {serial}: {click_error}")
                    return {"clicked": False, "reason": str(click_error)}
            else:
                return {"clicked": False, "reason": "Allow button not found"}

        except Exception as e:
            print(f"Error clicking Allow on device {serial}: {e}")
            self.failed_connections.add(serial)
            return {"clicked": False, "reason": str(e)}

    def click_allow_all_devices(self):
        click_results = {}

        with ThreadPoolExecutor(max_workers=999) as executor:
            future_to_serial = {
                executor.submit(self.click_allow_on_device, serial): serial
                for serial in self.device_connections
            }

            for future in as_completed(future_to_serial):
                serial = future_to_serial[future]
                try:
                    result = future.result()
                    click_results[serial] = result
                except Exception as e:
                    print(f"Error processing device {serial}: {e}")
                    click_results[serial] = {"clicked": False, "reason": str(e)}

        return click_results

    def verify_permission_granted(self, serial):
        device = self.device_connections.get(serial)
        if not device:
            return False

        text_elements = self.get_text_elements_from_device(
            device, serial, allow_reconnect=False
        )

        has_permission_dialog = any(
            "allow access to phone data" in element["text"].lower()
            for element in text_elements
        )

        return not has_permission_dialog

    def verify_all_devices_parallel(self):
        verification_results = {}

        with ThreadPoolExecutor(max_workers=999) as executor:
            future_to_serial = {
                executor.submit(self.verify_permission_granted, serial): serial
                for serial in self.device_connections
            }

            for future in as_completed(future_to_serial):
                serial = future_to_serial[future]
                try:
                    result = future.result()
                    verification_results[serial] = result
                except Exception as e:
                    print(f"Error verifying device {serial}: {e}")
                    verification_results[serial] = False

        return verification_results

    def find_always_connect_button(self, text_elements):
        """Find the 'Always connect' button in the text elements"""
        for element in text_elements:
            if "always connect" in element["text"].lower() and element["clickable"]:
                return element["position"]
        return None

    def has_network_connection_notification(self, text_elements):
        """Check if the network connection notification is present"""
        return any(
            "without internet access" in element["text"].lower() and
            "you can connect only this time" in element["text"].lower()
            for element in text_elements
        )

    def click_always_connect_on_device(self, serial):
        try:
            device = self.device_connections.get(serial)
            if not device:
                return {"clicked": False, "reason": "Device not found"}

            text_elements = self.get_text_elements_from_device(device, serial)

            if not self.has_network_connection_notification(text_elements):
                return {"clicked": False, "reason": "No network connection notification found"}

            always_connect_position = self.find_always_connect_button(text_elements)

            if always_connect_position:
                x, y = always_connect_position
                try:
                    device.click(x, y)
                    print(f"Clicked 'Always connect' on device {serial} at coordinates ({x}, {y})")
                    return {"clicked": True, "coordinates": (x, y)}
                except Exception as click_error:
                    print(f"Click exception on {serial}: {click_error}")
                    return {"clicked": False, "reason": str(click_error)}
            else:
                return {"clicked": False, "reason": "'Always connect' button not found"}

        except Exception as e:
            print(f"Error clicking 'Always connect' on device {serial}: {e}")
            self.failed_connections.add(serial)
            return {"clicked": False, "reason": str(e)}

    def click_always_connect_all_devices(self):
        click_results = {}

        with ThreadPoolExecutor(max_workers=999) as executor:
            future_to_serial = {
                executor.submit(self.click_always_connect_on_device, serial): serial
                for serial in self.device_connections
            }

            for future in as_completed(future_to_serial):
                serial = future_to_serial[future]
                try:
                    result = future.result()
                    click_results[serial] = result
                except Exception as e:
                    print(f"Error processing device {serial}: {e}")
                    click_results[serial] = {"clicked": False, "reason": str(e)}

        return click_results

    def get_current_state_parallel(self):
        current_state = {}

        with ThreadPoolExecutor(max_workers=999) as executor:
            future_to_serial = {}
            for serial in self.device_connections:
                device = self.device_connections[serial]
                future = executor.submit(
                    self.get_text_elements_from_device, device, serial
                )
                future_to_serial[future] = serial

            for future in as_completed(future_to_serial):
                serial = future_to_serial[future]
                try:
                    text_elements = future.result()
                    current_state[serial] = text_elements
                except Exception as e:
                    print(f"Error getting text elements for device {serial}: {e}")
                    current_state[serial] = []

        return current_state

    def reconnect_all_devices_parallel(self):
        if self.failed_connections:
            print(f"Reconnecting {len(self.failed_connections)} failed devices...")
            self.reconnect_devices_batch(self.failed_connections)

    def handle_permissions(self):
        print(f"Processing permissions for {len(self.device_connections)} devices...")

        current_state = self.get_current_state_parallel()

        devices_with_dialogs = []
        devices_with_network_notification = []

        for serial, text_elements in current_state.items():
            has_dialog = any(
                "allow access to phone data" in element["text"].lower()
                for element in text_elements
            )
            if has_dialog:
                devices_with_dialogs.append(serial)

            if self.has_network_connection_notification(text_elements):
                devices_with_network_notification.append(serial)

        verification_results = {}

        if not devices_with_dialogs:
            print("No permission dialogs found on any device.")

            for serial in self.device_connections:
                verification_results[serial] = {
                    "clicked": False,
                    "verified": False,
                    "had_dialog": False,
                    "details": {"reason": "No permission dialog"},
                }
        else:
            print(f"Found permission dialogs on {len(devices_with_dialogs)} devices")

            print("\nClicking Allow buttons...")
            click_results = self.click_allow_all_devices()

            print("\nVerifying permission grants...")
            verified_states = self.verify_all_devices_parallel()

            for serial, result in click_results.items():
                if result["clicked"]:
                    verified = verified_states.get(serial, False)
                    verification_results[serial] = {
                        "clicked": True,
                        "verified": verified,
                        "had_dialog": serial in devices_with_dialogs,
                        "details": result,
                    }
                    status = "SUCCESS" if verified else "PENDING"
                    if result.get("verified_success"):
                        status += " (verified immediately)"
                    if result.get("retry"):
                        status += " (after retry)"
                    print(f"Device {serial}: {status}")
                else:
                    verification_results[serial] = {
                        "clicked": False,
                        "verified": False,
                        "had_dialog": serial in devices_with_dialogs,
                        "details": result,
                    }
                    print(
                        f"Device {serial}: FAILED - {result.get('reason', 'Unknown')}"
                    )

        print("\nChecking for lock screen notifications...")
        lock_screen_dismissals = self.dismiss_lock_screen_all_devices()

        dismissed_count = sum(
            1 for dismissed in lock_screen_dismissals.values() if dismissed
        )
        if dismissed_count > 0:
            print(f"Accepted lock screen notifications on {dismissed_count} devices")

        for serial in verification_results:
            verification_results[serial]["lock_screen_accepted"] = (
                lock_screen_dismissals.get(serial, False)
            )

        # Handle network connection notifications
        print("\nChecking for network connection notifications...")
        if not devices_with_network_notification:
            print("No network connection notifications found on any device.")
            always_connect_results = {}
        else:
            print(f"Found network connection notifications on {len(devices_with_network_notification)} devices")
            always_connect_results = self.click_always_connect_all_devices()

            always_connect_count = sum(
                1 for result in always_connect_results.values() if result.get("clicked")
            )
            if always_connect_count > 0:
                print(f"Clicked 'Always connect' on {always_connect_count} devices")

        for serial in verification_results:
            verification_results[serial]["always_connect_clicked"] = (
                always_connect_results.get(serial, {}).get("clicked", False)
            )

        return {
            "results": verification_results,
            "lock_screen_dismissals": lock_screen_dismissals,
            "always_connect_results": always_connect_results,
        }


def main():
    handler = DevicePermissionHandler()
    handler.monitor.print_device_summary()

    print("\nSearching for permission dialogs and lock screen notifications...")

    results = handler.handle_permissions()

    if not results:
        print("No operations performed.")
        return

    print("\nOperation completed.")
    print("\nSummary:")

    if "lock_screen_dismissals" in results:
        dismissed_count = sum(
            1 for d in results["lock_screen_dismissals"].values() if d
        )
        if dismissed_count > 0:
            print(f"Lock screen notifications accepted: {dismissed_count} devices")

    if "always_connect_results" in results:
        always_connect_count = sum(
            1 for r in results["always_connect_results"].values() if r.get("clicked")
        )
        if always_connect_count > 0:
            print(f"'Always connect' clicked: {always_connect_count} devices")

    if results.get("results"):
        successful = 0
        failed = 0
        no_dialog = 0

        for serial, result in results["results"].items():
            status_parts = []

            if result["had_dialog"]:
                if result["clicked"] and result["verified"]:
                    status_parts.append("Permission granted ✔")
                    successful += 1
                elif result["clicked"] and not result["verified"]:
                    status_parts.append("Clicked but verification failed ⚠")
                    failed += 1
                else:
                    reason = result.get("details", {}).get("reason", "Unknown")
                    status_parts.append(f"Could not click Allow button ✗ ({reason})")
                    failed += 1
            else:
                status_parts.append("No permission dialog found")
                no_dialog += 1

            if result.get("lock_screen_accepted"):
                status_parts.append("Lock screen accepted")

            if result.get("always_connect_clicked"):
                status_parts.append("'Always connect' clicked")

            print(f"  {serial}: {', '.join(status_parts)}")

        if successful > 0 or failed > 0:
            print(
                f"\nTotal permissions: {successful} successful, {failed} failed, {no_dialog} no dialog"
            )
        else:
            print(f"\nNo permission dialogs found on {no_dialog} devices")


if __name__ == "__main__":
    main()
