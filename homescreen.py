#!/usr/bin/env python3

import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed


def get_connected_devices():
    result = subprocess.run(['adb', 'devices'], capture_output=True, text=True)
    devices = []
    for line in result.stdout.strip().split('\n')[1:]:
        if '\tdevice' in line:
            device_id = line.split('\t')[0]
            devices.append(device_id)
    return devices

def send_to_home(device_id):
    try:
        result = subprocess.run(
            ['adb', '-s', device_id, 'shell', 'input', 'keyevent', 'KEYCODE_HOME'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return f"✓ {device_id}: Successfully sent to home screen"
        else:
            return f"✗ {device_id}: Failed - {result.stderr.strip()}"
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
    print("Sending all devices to home screen in parallel...\n")

    with ThreadPoolExecutor(max_workers=len(devices)) as executor:
        futures = {executor.submit(send_to_home, device): device for device in devices}

        for future in as_completed(futures):
            result = future.result()
            print(result)

    print(f"\nCompleted processing {len(devices)} device(s)")

if __name__ == "__main__":
    main()
