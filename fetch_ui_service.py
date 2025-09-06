import base64
import io
import json
import os
import re
import threading
import time
import traceback
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from functools import lru_cache
from queue import Queue

from PIL import Image

from cache_device_connection import DeviceConnectionClient


class FetchViewService:
    def __init__(self, output_dir="ui_captures", max_workers=999):
        self.output_dir = output_dir
        self.max_workers = max_workers
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.io_executor = ThreadPoolExecutor(max_workers=max_workers)
        self.ensure_output_dir()
        self.hierarchy_cache = {}
        self.cache_lock = threading.Lock()
        self.write_queue = Queue()
        self.start_write_worker()
        self.client = DeviceConnectionClient(auto_start_service=True)
        self.devices = self._get_devices()

    def _get_devices(self):
        result = self.client.discover_devices()
        if result.get("status") == "success":
            return result.get("data", {})
        return {}

    def ensure_output_dir(self):
        os.makedirs(self.output_dir, exist_ok=True)

    def start_write_worker(self):
        def write_worker():
            while True:
                item = self.write_queue.get()
                if item is None:
                    break
                filepath, data, is_binary, should_rotate = item
                try:
                    if is_binary:
                        if should_rotate:
                            img = Image.open(io.BytesIO(data))
                            rotated_img = img.rotate(270, expand=True)
                            rotated_img.save(filepath, "PNG")
                        else:
                            with open(filepath, "wb") as f:
                                f.write(data)
                    else:
                        with open(filepath, "w", encoding="utf-8") as f:
                            json.dump(data, f, indent=2, ensure_ascii=False)
                except Exception as e:
                    print(f"Write error to {filepath}: {e}")
                finally:
                    self.write_queue.task_done()

        thread = threading.Thread(target=write_worker, daemon=True)
        thread.start()

    def parse_bounds(self, bounds_str):
        if not bounds_str:
            return (0, 0, 0, 0)
        match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds_str)
        return tuple(map(int, match.groups())) if match else (0, 0, 0, 0)

    def parse_hierarchy_simple(self, xml_string):
        try:
            root = ET.fromstring(xml_string)
            elements = []

            def process_node(node, depth=0):
                bounds = node.get("bounds", "")
                x1, y1, x2, y2 = self.parse_bounds(bounds)

                elem_dict = {
                    "depth": depth,
                    "class": node.get("class", ""),
                    "text": node.get("text", ""),
                    "content_desc": node.get("content-desc", ""),
                    "resource_id": node.get("resource-id", ""),
                    "package": node.get("package", ""),
                    "clickable": node.get("clickable") == "true",
                    "scrollable": node.get("scrollable") == "true",
                    "focusable": node.get("focusable") == "true",
                    "enabled": node.get("enabled") == "true",
                    "selected": node.get("selected") == "true",
                    "checked": node.get("checked") == "true",
                    "checkable": node.get("checkable") == "true",
                    "long_clickable": node.get("long-clickable") == "true",
                    "password": node.get("password") == "true",
                    "bounds": bounds,
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                    "width": x2 - x1,
                    "height": y2 - y1,
                    "center_x": (x1 + x2) // 2,
                    "center_y": (y1 + y2) // 2,
                    "index": node.get("index", ""),
                    "instance": node.get("instance", ""),
                }

                elements.append(elem_dict)

                for child in node:
                    process_node(child, depth + 1)

            process_node(root)
            return elements
        except Exception as e:
            print(f"Error parsing hierarchy: {e}")
            return []

    def capture_device_state_via_service(self, serial, capture_dir=None):
        try:
            hierarchy_result = self.client.dump_hierarchy(
                serial, compressed=False, pretty=False
            )

            if hierarchy_result.get("status") != "success":
                print(
                    f"Failed to dump hierarchy for {serial}: {hierarchy_result.get('message', 'Unknown error')}"
                )
                return None

            hierarchy_xml = hierarchy_result.get("data", "")
            if not hierarchy_xml:
                print(f"Empty hierarchy for {serial}")
                return None

            elements = self.parse_hierarchy_simple(hierarchy_xml)

            app_result = self.client.get_app_current(serial)
            current_app = {"activity": "", "package": ""}
            if app_result.get("status") == "success":
                current_app = app_result.get("data", {"activity": "", "package": ""})

            info_result = self.client.get_device_info(serial)
            screen_info = {"width": 0, "height": 0, "rotation": 0}
            if info_result.get("status") == "success":
                device_info = info_result.get("data", {})
                screen_info = {
                    "width": device_info.get("displayWidth", 0),
                    "height": device_info.get("displayHeight", 0),
                    "rotation": device_info.get("displayRotation", 0),
                }

            device_info = self.devices.get(serial, {})

            state = {
                "timestamp": time.time(),
                "datetime": datetime.now().isoformat(),
                "device_serial": serial,
                "device_info": {"model": device_info.get("model", "Unknown")},
                "screen_info": screen_info,
                "current_app": current_app,
                "total_elements": len(elements),
                "elements": elements,
            }

            if capture_dir:
                try:
                    device_model = device_info.get("model", "unknown").replace(" ", "_")
                    screenshot_path = os.path.join(
                        capture_dir, f"screenshot_{device_model}_{serial}.png"
                    )

                    screenshot_result = self.client.take_screenshot(
                        serial, filepath=None
                    )

                    if screenshot_result.get("status") == "success":
                        img_b64 = screenshot_result.get("data", "")
                        if img_b64:
                            img_bytes = base64.b64decode(img_b64)
                            self.write_queue.put(
                                (screenshot_path, img_bytes, True, True)
                            )
                            state["screenshot_path"] = screenshot_path
                            print(f"  ✓ Screenshot queued for {serial}")
                except Exception as e:
                    print(f"  ✗ Screenshot failed for {serial}: {e}")

            return state

        except Exception as e:
            print(f"✗ Error capturing state for device {serial}: {str(e)}")
            traceback.print_exc()
            return None

    def capture_all_devices_parallel(self, capture_dir=None):
        states = {}
        futures = {}

        print(f"\nStarting parallel capture for {len(self.devices)} devices...")

        for serial in self.devices:
            future = self.executor.submit(
                self.capture_device_state_via_service, serial, capture_dir
            )
            futures[future] = serial

        completed = 0
        for future in as_completed(futures):
            serial = futures[future]
            completed += 1
            try:
                state = future.result()
                if state:
                    states[serial] = state
                    print(f"✓ Completed {completed}/{len(self.devices)}: {serial}")
                else:
                    print(
                        f"✗ Failed {completed}/{len(self.devices)}: {serial} - No state returned"
                    )
            except Exception as e:
                print(f"✗ Error {completed}/{len(self.devices)}: {serial} - {str(e)}")

        print(f"\nCapture complete: {len(states)}/{len(self.devices)} successful")
        return states

    def create_capture_directory(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        capture_dir = os.path.join(self.output_dir, timestamp)
        os.makedirs(capture_dir, exist_ok=True)
        return capture_dir

    def save_states_to_files_parallel(self, states, capture_dir):
        for serial, state in states.items():
            device_model = (
                state["device_info"].get("model", "unknown").replace(" ", "_")
            )
            filename = f"ui_hierarchy_{device_model}_{serial}.json"
            filepath = os.path.join(capture_dir, filename)

            self.write_queue.put((filepath, state, False, False))
            print(f"Queued save for {serial} to {filepath}")

    def capture_single_snapshot(self, take_screenshots=True):
        if take_screenshots:
            capture_dir = self.create_capture_directory()
        else:
            capture_dir = None

        states = self.capture_all_devices_parallel(capture_dir)

        if states and capture_dir:
            self.save_states_to_files_parallel(states, capture_dir)

        return states, capture_dir

    def print_device_summary(self):
        print(f"\nConnected Devices ({len(self.devices)}):")
        for serial, info in self.devices.items():
            print(
                f"  {serial}: {info.get('model', 'Unknown')} (connected: {info.get('connected_at', 'Unknown')})"
            )

    def refresh_devices(self):
        print("Refreshing device list...")
        self.devices = self._get_devices()
        self.print_device_summary()

    def wait_for_queue_completion(self):
        self.write_queue.join()

    def __del__(self):
        try:
            self.write_queue.put(None)
            self.executor.shutdown(wait=False)
            self.io_executor.shutdown(wait=False)
        except:
            pass


if __name__ == "__main__":
    try:
        print("═" * 60)
        print("FetchView with Service-Based Persistent Connections")
        print("═" * 60)

        monitor = FetchViewService(max_workers=999)
        monitor.print_device_summary()

        print(f"\nCapturing snapshot with screenshots...")
        states, capture_dir = monitor.capture_single_snapshot(take_screenshots=True)

        if states and capture_dir:
            print(f"\n✓ Capture completed successfully!")
            print(f"📁 Files saved to: {capture_dir}")

            monitor.wait_for_queue_completion()

            files = os.listdir(capture_dir)
            json_files = [f for f in files if f.endswith(".json")]
            png_files = [f for f in files if f.endswith(".png")]

            print(f"\n📊 Capture Summary:")
            print(f"   • UI Hierarchies: {len(json_files)}")
            print(f"   • Screenshots: {len(png_files)}")
            print(f"   • Total Files: {len(files)}")

            if png_files:
                print(f"\n📸 Screenshots saved:")
                for png in png_files[:999]:
                    print(f"   • {png}")
        else:
            print("\n✗ No captures were successful")

    except Exception as e:
        print(f"Fatal error: {e}")
        traceback.print_exc()
