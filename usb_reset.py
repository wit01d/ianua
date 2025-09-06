#!/usr/bin/env python3

import glob
import os
import subprocess
import sys
import time
from pathlib import Path


class USBSamsungReset:
    SAMSUNG_VENDOR_ID = "04e8"
    SAMSUNG_PRODUCT_ID = "6860"

    def __init__(self):
        self.sysfs_path = "/sys/bus/usb/devices"
        self.driver_path = "/sys/bus/usb/drivers/usb"

    def find_samsung_devices(self):
        devices = []

        for device_path in glob.glob(f"{self.sysfs_path}/*"):
            vendor_file = Path(device_path) / "idVendor"
            product_file = Path(device_path) / "idProduct"

            if vendor_file.exists() and product_file.exists():
                try:
                    vendor = vendor_file.read_text().strip()
                    product = product_file.read_text().strip()

                    if (
                        vendor == self.SAMSUNG_VENDOR_ID
                        and product == self.SAMSUNG_PRODUCT_ID
                    ):
                        device_id = os.path.basename(device_path)

                        busnum_file = Path(device_path) / "busnum"
                        devnum_file = Path(device_path) / "devnum"

                        busnum = (
                            busnum_file.read_text().strip()
                            if busnum_file.exists()
                            else "N/A"
                        )
                        devnum = (
                            devnum_file.read_text().strip()
                            if devnum_file.exists()
                            else "N/A"
                        )

                        devices.append(
                            {
                                "id": device_id,
                                "path": device_path,
                                "bus": busnum,
                                "device": devnum,
                            }
                        )
                except:
                    continue

        return devices

    def reset_device(self, device_id):
        unbind_path = Path(self.driver_path) / "unbind"
        bind_path = Path(self.driver_path) / "bind"

        try:
            print(f"Unbinding device {device_id}...")
            unbind_path.write_text(device_id)
            time.sleep(1)

            print(f"Binding device {device_id}...")
            bind_path.write_text(device_id)
            time.sleep(1)

            print(f"Device {device_id} reset complete")
            return True

        except PermissionError:
            print(f"Permission denied. Run with sudo.")
            return False
        except Exception as e:
            print(f"Error resetting device {device_id}: {e}")
            return False

    def reset_all_samsung_devices(self):
        devices = self.find_samsung_devices()

        if not devices:
            print("No Samsung devices found")
            return

        print(f"Found {len(devices)} Samsung device(s)")

        for device in devices:
            print(
                f"\nResetting device: {device['id']} (Bus {device['bus']}, Device {device['device']})"
            )
            self.reset_device(device["id"])
            time.sleep(2)

    def reset_by_bus_device(self, bus_num, device_num):
        devices = self.find_samsung_devices()

        for device in devices:
            if device["bus"] == str(bus_num) and device["device"] == str(device_num):
                return self.reset_device(device["id"])

        print(f"No device found at Bus {bus_num}, Device {device_num}")
        return False

    def reset_by_port(self, hub_device, port):
        authorized_path = (
            Path(self.sysfs_path) / hub_device / f"{hub_device}.{port}" / "authorized"
        )

        if not authorized_path.exists():
            print(f"Port path not found: {authorized_path}")
            return False

        try:
            print(f"Disabling port {port} on hub {hub_device}...")
            authorized_path.write_text("0")
            time.sleep(1)

            print(f"Enabling port {port} on hub {hub_device}...")
            authorized_path.write_text("1")
            time.sleep(1)

            print(f"Port reset complete")
            return True

        except PermissionError:
            print(f"Permission denied. Run with sudo.")
            return False
        except Exception as e:
            print(f"Error resetting port: {e}")
            return False

    def list_devices(self):
        devices = self.find_samsung_devices()

        if not devices:
            print("No Samsung devices found")
            return

        print(f"\nSamsung devices found ({len(devices)} total):")
        print("=" * 50)

        for device in devices:
            print(
                f"Device ID: {device['id']:<15} Bus: {device['bus']:<3} Device: {device['device']:<3}"
            )

    def monitor_devices(self, interval=2):
        print(
            f"Monitoring Samsung devices (refresh every {interval}s, Ctrl+C to stop)..."
        )

        previous_devices = set()

        try:
            while True:
                current_devices = set(d["id"] for d in self.find_samsung_devices())

                added = current_devices - previous_devices
                removed = previous_devices - current_devices

                if added:
                    for device_id in added:
                        print(f"[+] Device connected: {device_id}")

                if removed:
                    for device_id in removed:
                        print(f"[-] Device disconnected: {device_id}")

                previous_devices = current_devices
                time.sleep(interval)

        except KeyboardInterrupt:
            print("\nMonitoring stopped")

    def batch_reset(self, device_ids):
        for device_id in device_ids:
            print(f"\nResetting device: {device_id}")
            self.reset_device(device_id)
            time.sleep(2)


def main():
    if os.geteuid() != 0:
        print("Warning: Running without root privileges. Some operations may fail.")

    reset_tool = USBSamsungReset()

    if len(sys.argv) < 2:
        print("USB Samsung Device Reset Tool")
        print("=" * 50)
        print("\nUsage:")
        print("  python3 usb_reset.py all                  - Reset all Samsung devices")
        print("  python3 usb_reset.py device <bus> <dev>   - Reset specific device")
        print("  python3 usb_reset.py port <hub_id> <port> - Reset device on hub port")
        print("  python3 usb_reset.py list                 - List all Samsung devices")
        print(
            "  python3 usb_reset.py monitor              - Monitor device connections"
        )
        print(
            "  python3 usb_reset.py batch <id1> <id2>... - Reset multiple devices by ID"
        )
        print("\nExamples:")
        print("  sudo python3 usb_reset.py all")
        print("  sudo python3 usb_reset.py device 9 126")
        print("  sudo python3 usb_reset.py port 1-3.1.4 3")
        print("  sudo python3 usb_reset.py batch 1-3.1.4.3:1.0 1-3.1.4.1:1.0")
        sys.exit(1)

    command = sys.argv[1]

    if command == "all":
        reset_tool.reset_all_samsung_devices()

    elif command == "device":
        if len(sys.argv) != 4:
            print("Usage: python3 usb_reset.py device <bus_number> <device_number>")
            sys.exit(1)
        reset_tool.reset_by_bus_device(sys.argv[2], sys.argv[3])

    elif command == "port":
        if len(sys.argv) != 4:
            print("Usage: python3 usb_reset.py port <hub_device_id> <port_number>")
            sys.exit(1)
        reset_tool.reset_by_port(sys.argv[2], sys.argv[3])

    elif command == "list":
        reset_tool.list_devices()

    elif command == "monitor":
        interval = int(sys.argv[2]) if len(sys.argv) > 2 else 2
        reset_tool.monitor_devices(interval)

    elif command == "batch":
        if len(sys.argv) < 3:
            print("Usage: python3 usb_reset.py batch <device_id1> <device_id2> ...")
            sys.exit(1)
        reset_tool.batch_reset(sys.argv[2:])

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
