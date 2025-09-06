import concurrent.futures
import time

from cache_device_connection import DeviceConnectionClient


def reboot_device(client, serial, info):
    """Reboot a single device and return the result."""
    print(f"Rebooting {serial} ({info.get('model', 'Unknown')})")

    print(f"  Sending reboot command to {serial}")
    reboot_result = client.execute_action(serial, "shell", command="reboot")

    if reboot_result.get("status") == "success":
        result = f"  ✓ Reboot command sent successfully to {serial}"
    elif "shell output invalid" in str(
        reboot_result.get("message", "")
    ) and "reboot;" in str(reboot_result.get("message", "")):

        result = f"  ✓ Reboot likely successful for {serial} (connection terminated as expected)"
    else:
        result = f"  ✗ Failed to send reboot command to {serial}: {reboot_result.get('message')}"

    print(result)
    print(f"  Completed operations for {serial}\n")
    return serial, result


def main():
    client = DeviceConnectionClient(auto_start_service=True)

    print("Discovering devices...")
    result = client.discover_devices()

    if result.get("status") != "success":
        print(f"Failed to discover devices: {result.get('message')}")
        return

    devices = result.get("data", {})
    print(f"Found {len(devices)} device(s)")

    if not devices:
        print("No devices found to reboot")
        return

    print("\nRebooting devices in parallel:")
    with concurrent.futures.ThreadPoolExecutor() as executor:

        future_to_serial = {
            executor.submit(reboot_device, client, serial, info): serial
            for serial, info in devices.items()
        }

        for future in concurrent.futures.as_completed(future_to_serial):
            serial = future_to_serial[future]
            try:
                future.result()
            except Exception as e:
                print(f"  ! Exception occurred while rebooting {serial}: {e}")

    print("All reboot operations completed.")


if __name__ == "__main__":
    main()
