#!/usr/bin/env python3

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from cache_device_connection import DeviceConnectionClient


def scroll_to_bottom(client, serial, max_scrolls=20):
    print(f"  📜 Scrolling to bottom...")

    device_info_result = client.get_device_info(serial)
    if device_info_result.get("status") != "success":
        print(f"  ⚠ Could not get device info, using default scroll parameters")
        screen_width = 1080
        screen_height = 1920
    else:
        device_info = device_info_result.get("data", {})
        screen_width = device_info.get("displayWidth", 1080)
        screen_height = device_info.get("displayHeight", 1920)

    print(f"  📱 Screen dimensions: {screen_width}x{screen_height}")

    start_x = screen_width // 2
    start_y = int(screen_height * 0.8)
    end_y = int(screen_height * 0.2)

    scroll_distance = start_y - end_y
    print(f"  📏 Scroll distance: {scroll_distance}px")

    previous_hierarchy = None
    unchanged_count = 0

    for scroll_attempt in range(max_scrolls):
        try:

            swipe_result = client.execute_action(
                serial=serial,
                action="swipe",
                fx=start_x,
                fy=start_y,
                tx=start_x,
                ty=end_y,
                duration=0.3,
            )

            if swipe_result.get("status") != "success":
                print(f"  ⚠ Scroll attempt {scroll_attempt + 1} failed")
                continue

            time.sleep(0.8)

            hierarchy_result = client.dump_hierarchy(
                serial, compressed=False, pretty=False
            )
            if hierarchy_result.get("status") == "success":
                current_hierarchy = hierarchy_result.get("data", "")

                if current_hierarchy == previous_hierarchy:
                    unchanged_count += 1
                    if unchanged_count >= 2:
                        print(f"  ✅ Reached bottom after {scroll_attempt + 1} scrolls")
                        return True
                else:
                    unchanged_count = 0
                    previous_hierarchy = current_hierarchy

            print(f"  📜 Scroll {scroll_attempt + 1}/{max_scrolls} completed")

            time.sleep(0.5)

        except Exception as e:
            print(f"  ⚠ Error during scroll {scroll_attempt + 1}: {str(e)}")
            continue

    print(f"  ⚠ Completed {max_scrolls} scrolls (may have reached bottom)")
    return True


def process_single_device(serial, device_info, client):
    device_model = device_info.get("model", "Unknown")
    print(f"\n🔧 Processing {serial} ({device_model})")

    try:

        app_result = client.get_app_current(serial)
        if app_result.get("status") != "success":
            return serial, False, f"Device not responsive"

        print(f"  📱 Opening Settings app...")
        settings_result = client.execute_action(
            serial=serial, action="app_start", package_name="com.android.settings"
        )

        if settings_result.get("status") != "success":
            error_msg = settings_result.get("message", "Unknown error")
            return serial, False, f"Failed to open Settings: {error_msg}"

        print(f"  ✅ Settings opened successfully")

        time.sleep(2)

        current_app = client.get_app_current(serial)
        if current_app.get("status") == "success":
            app_info = current_app.get("data", {})
            current_package = app_info.get("package", "")
            if "settings" not in current_package.lower():
                print(
                    f"  ⚠ Warning: Expected Settings, but current app is {current_package}"
                )

        scroll_success = scroll_to_bottom(client, serial)

        if scroll_success:
            print(f"  🎉 Successfully opened Settings and scrolled to bottom")
            return serial, True, None
        else:
            return serial, False, "Scrolling failed"

    except Exception as e:
        return serial, False, f"Error processing device: {str(e)}"


def open_settings_and_scroll_parallel():
    print("═" * 70)
    print("Opening Settings and Scrolling to Bottom on All Devices")
    print("═" * 70)

    client = DeviceConnectionClient(auto_start_service=True)

    print("\n1️⃣ Checking service status...")
    status = client.get_service_status()
    if status.get("status") != "success":
        print(f"❌ Service error: {status.get('message')}")
        return False

    print("✅ Device Connection Service is running")

    print("\n2️⃣ Discovering connected devices...")
    result = client.discover_devices()

    if result.get("status") != "success":
        print(f"❌ Failed to discover devices: {result.get('message')}")
        return False

    devices = result.get("data", {})
    if not devices:
        print("⚠️  No devices found. Make sure devices are:")
        print("   • Connected via USB")
        print("   • Have USB debugging enabled")
        print("   • Are authorized for ADB access")
        return False

    print(f"✅ Found {len(devices)} device(s):")
    for serial, info in devices.items():
        print(f"   • {serial}: {info.get('model', 'Unknown')}")

    print(f"\n3️⃣ Processing all devices in parallel...")

    success_count = 0
    failed_devices = []

    max_workers = min(len(devices), 10)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:

        futures = {
            executor.submit(process_single_device, serial, info, client): serial
            for serial, info in devices.items()
        }

        for future in as_completed(futures):
            serial = futures[future]
            try:
                serial_result, success, error_msg = future.result()

                if success:
                    success_count += 1
                    print(f"✅ {serial}: Completed successfully")
                else:
                    failed_devices.append((serial, error_msg))
                    print(f"❌ {serial}: {error_msg}")

            except Exception as e:
                failed_devices.append((serial, f"Unexpected error: {str(e)}"))
                print(f"❌ {serial}: Unexpected error: {str(e)}")

    print(f"\n" + "═" * 70)
    print(f"📊 Final Summary:")
    print(f"   • Total devices: {len(devices)}")
    print(f"   • Successful: {success_count}")
    print(f"   • Failed: {len(failed_devices)}")

    if failed_devices:
        print(f"\n❌ Failed devices:")
        for serial, error in failed_devices:
            device_info = devices.get(serial, {})
            model = device_info.get("model", "Unknown")
            print(f"   • {serial} ({model}): {error}")

    if success_count == len(devices):
        print(f"\n🎉 All devices successfully processed!")
    elif success_count > 0:
        print(f"\n⚠️  Partial success - check failed devices above")
    else:
        print(f"\n❌ No devices successfully processed")

    print("═" * 70)
    return success_count > 0


def open_settings_and_scroll_single(device_serial):
    print(f"Opening Settings and scrolling to bottom on device: {device_serial}")

    client = DeviceConnectionClient(auto_start_service=True)

    discovery_result = client.discover_devices()
    if discovery_result.get("status") != "success":
        print(f"❌ Failed to discover devices")
        return False

    devices = discovery_result.get("data", {})
    if device_serial not in devices:
        print(f"❌ Device {device_serial} not found in connected devices")
        available = list(devices.keys())
        if available:
            print(f"Available devices: {', '.join(available)}")
        return False

    device_info = devices[device_serial]
    serial, success, error_msg = process_single_device(
        device_serial, device_info, client
    )

    if success:
        print("🎉 Successfully completed!")
        return True
    else:
        print(f"❌ Failed: {error_msg}")
        return False


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:

        device_serial = sys.argv[1]
        open_settings_and_scroll_single(device_serial)
    else:

        open_settings_and_scroll_parallel()
