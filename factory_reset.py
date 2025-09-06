#!/usr/bin/env python3

import os
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


def get_connected_devices():
    result = subprocess.run(["adb", "devices"], capture_output=True, text=True)
    devices = []
    for line in result.stdout.strip().split("\n")[1:]:
        if "\tdevice" in line:
            device_id = line.split("\t")[0]
            devices.append(device_id)
    return devices


def find_and_click_element(device_id, xml_content, target_texts, step_name):
    try:
        root = ET.fromstring(xml_content)
        coordinates = None
        found_text = None

        for text in target_texts:
            for node in root.iter("node"):
                node_text = node.get("text", "")
                content_desc = node.get("content-desc", "")

                if (
                    text.lower() in node_text.lower()
                    or text.lower() in content_desc.lower()
                ):
                    bounds = node.get("bounds", "")
                    match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
                    if match:
                        x1, y1, x2, y2 = map(int, match.groups())
                        center_x = (x1 + x2) // 2
                        center_y = (y1 + y2) // 2
                        coordinates = (center_x, center_y)
                        found_text = text
                        break
            if coordinates:
                break

        if coordinates:
            subprocess.run(
                [
                    "adb",
                    "-s",
                    device_id,
                    "shell",
                    "input",
                    "tap",
                    str(coordinates[0]),
                    str(coordinates[1]),
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return (
                True,
                f"{step_name}: Clicked '{found_text}' at ({coordinates[0]}, {coordinates[1]})",
            )
        else:
            return False, f"{step_name}: Target not found"
    except Exception as e:
        return False, f"{step_name}: Error - {str(e)}"


def capture_ui_dump(device_id, dump_suffix):
    ui_captures_dir = Path("ui_captures")
    ui_captures_dir.mkdir(exist_ok=True)

    local_dump_path = ui_captures_dir / f"{device_id}_{dump_suffix}.xml"
    device_dump_path = "/sdcard/window_dump.xml"

    subprocess.run(
        ["adb", "-s", device_id, "shell", "rm", "-f", device_dump_path],
        capture_output=True,
        text=True,
        timeout=5,
    )

    dump_result = subprocess.run(
        ["adb", "-s", device_id, "shell", "uiautomator", "dump", device_dump_path],
        capture_output=True,
        text=True,
        timeout=10,
    )

    if dump_result.returncode != 0:
        dump_result = subprocess.run(
            ["adb", "-s", device_id, "shell", "uiautomator", "dump"],
            capture_output=True,
            text=True,
            timeout=10,
        )

    time.sleep(0.5)

    cat_result = subprocess.run(
        ["adb", "-s", device_id, "shell", "cat", device_dump_path],
        capture_output=True,
        text=True,
        timeout=10,
    )

    if cat_result.returncode != 0:
        raise Exception(f"Failed to read UI dump: {cat_result.stderr}")

    xml_content = cat_result.stdout.strip()

    if (
        not xml_content
        or not xml_content.startswith("<?xml")
        and not xml_content.startswith("<hierarchy")
    ):
        subprocess.run(
            ["adb", "-s", device_id, "pull", device_dump_path, str(local_dump_path)],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if local_dump_path.exists():
            with open(local_dump_path, "r", encoding="utf-8") as f:
                xml_content = f.read()
        else:
            raise Exception("Failed to retrieve UI dump")

    with open(local_dump_path, "w", encoding="utf-8") as f:
        f.write(xml_content)

    subprocess.run(
        ["adb", "-s", device_id, "shell", "rm", "-f", device_dump_path],
        capture_output=True,
        text=True,
        timeout=5,
    )

    return xml_content


def perform_network_reset(device_id):
    try:
        results = []

        subprocess.run(
            [
                "adb",
                "-s",
                device_id,
                "shell",
                "am",
                "start",
                "-a",
                "android.settings.SETTINGS",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )

        time.sleep(2)

        xml_content = capture_ui_dump(device_id, "1_settings_main")
        success, message = find_and_click_element(
            device_id,
            xml_content,
            ["General management", "General", "Device care", "System"],
            "Step 1",
        )
        results.append(message)

        if not success:
            return f"✗ {device_id}: Failed at General Management\n  - {message}"

        time.sleep(2)

        xml_content = capture_ui_dump(device_id, "2_general_management")
        success, message = find_and_click_element(
            device_id,
            xml_content,
            ["Reset", "Reset options", "Reset settings"],
            "Step 2",
        )
        results.append(message)

        if not success:
            return f"✗ {device_id}: Failed at Reset\n  - " + "\n  - ".join(results)

        time.sleep(2)

        xml_content = capture_ui_dump(device_id, "3_reset_options")
        success, message = find_and_click_element(
            device_id,
            xml_content,
            ["Reset network settings", "Network settings reset", "Reset Wi-Fi"],
            "Step 3",
        )
        results.append(message)

        if not success:
            return (
                f"✗ {device_id}: Failed at Reset network settings\n  - "
                + "\n  - ".join(results)
            )

        time.sleep(2)

        xml_content = capture_ui_dump(device_id, "4_network_reset_page")
        success, message = find_and_click_element(
            device_id, xml_content, ["Reset settings", "Reset"], "Step 4"
        )
        results.append(message)

        if not success:
            return (
                f"✗ {device_id}: Failed at Reset settings button\n  - "
                + "\n  - ".join(results)
            )

        time.sleep(2)

        xml_content = capture_ui_dump(device_id, "5_confirmation_dialog")
        success, message = find_and_click_element(
            device_id,
            xml_content,
            ["Reset", "Reset settings", "Confirm", "OK", "Yes"],
            "Step 5",
        )
        results.append(message)

        if success:
            return (
                f"✓ {device_id}: Successfully completed network reset\n  - "
                + "\n  - ".join(results)
            )
        else:
            return f"✗ {device_id}: Failed at confirmation\n  - " + "\n  - ".join(
                results
            )

    except subprocess.TimeoutExpired:
        return f"✗ {device_id}: Command timed out"
    except Exception as e:
        return f"✗ {device_id}: Error - {str(e)}"


def main():
    devices = get_connected_devices()

    if not devices:
        print("No devices connected")
        return

    print(f"Found {len(devices)} device(s)")
    print("Performing complete network reset on all devices...")
    print(f"UI dumps will be saved to: {Path('ui_captures').absolute()}\n")

    with ThreadPoolExecutor(max_workers=len(devices)) as executor:
        futures = {
            executor.submit(perform_network_reset, device): device for device in devices
        }

        for future in as_completed(futures):
            result = future.result()
            print(result)
            print("-" * 60)

    print(f"\nCompleted processing {len(devices)} device(s)")


if __name__ == "__main__":
    main()
