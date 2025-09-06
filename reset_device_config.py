#!/usr/bin/env python3

import sys
import time

from cache_device_connection import DeviceConnectionClient


class DeviceSettingsReset:
    def __init__(self):
        self.client = DeviceConnectionClient(auto_start_service=True)
        self.devices = {}

    def discover_devices(self):
        print("═" * 60)
        print("DEVICE SETTINGS RESET UTILITY")
        print("═" * 60)

        print("\n📱 Discovering connected devices...")
        result = self.client.discover_devices()

        if result.get("status") == "success":
            self.devices = result.get("data", {})
            if self.devices:
                print(f"✓ Found {len(self.devices)} device(s):")
                for idx, (serial, info) in enumerate(self.devices.items(), 1):
                    print(f"  {idx}. {serial}: {info.get('model', 'Unknown')}")
                return True
            else:
                print("✗ No devices found. Make sure devices are connected via USB/ADB")
                return False
        else:
            print(f"✗ Discovery failed: {result.get('message')}")
            return False

    def reset_network_settings(self, serial):
        print(f"\n🌐 Resetting network settings for {serial}...")

        network_commands = [
            ("settings put global airplane_mode_on 0", "Disabling airplane mode"),
            ("settings put global wifi_on 1", "Enabling WiFi"),
            ("settings put global bluetooth_on 1", "Enabling Bluetooth"),
            (
                "content delete --uri content://settings/global --where \"name='network_selection_name'\"",
                "Clearing network selection",
            ),
            (
                "content delete --uri content://settings/global --where \"name='network_selection_short_name'\"",
                "Clearing network name",
            ),
            ("settings put global wifi_saved_state 1", "Restoring WiFi saved state"),
            (
                "settings put global wifi_scan_always_enabled 1",
                "Enabling WiFi scanning",
            ),
            (
                "cmd connectivity airplane-mode disable",
                "Ensuring airplane mode disabled",
            ),
        ]

        success_count = 0
        for cmd, description in network_commands:
            print(f"  • {description}...", end=" ")
            result = self.client.execute_action(serial, "shell", command=cmd)
            if result.get("status") == "success":
                print("✓")
                success_count += 1
            else:
                print(f"✗ ({result.get('message', 'Unknown error')})")

        return success_count == len(network_commands)

    def reset_wifi(self, serial):
        print(f"\n📶 Resetting WiFi for {serial}...")

        wifi_commands = [
            ("pm clear com.android.wifi", "Clearing WiFi data"),
            ("cmd wifi reset", "Resetting WiFi configuration"),
            ("settings put global wifi_on 1", "Re-enabling WiFi"),
        ]

        success_count = 0
        for cmd, description in wifi_commands:
            print(f"  • {description}...", end=" ")
            result = self.client.execute_action(serial, "shell", command=cmd)
            if result.get("status") == "success":
                print("✓")
                success_count += 1
            else:
                print(f"✗ ({result.get('message', 'Unknown error')})")

        return success_count == len(wifi_commands)

    def reset_bluetooth(self, serial):
        print(f"\n🔷 Resetting Bluetooth for {serial}...")

        bluetooth_commands = [
            ("pm clear com.android.bluetooth", "Clearing Bluetooth data"),
            ("cmd bluetooth_manager reset", "Resetting Bluetooth manager"),
            ("settings put global bluetooth_on 1", "Re-enabling Bluetooth"),
        ]

        success_count = 0
        for cmd, description in bluetooth_commands:
            print(f"  • {description}...", end=" ")
            result = self.client.execute_action(serial, "shell", command=cmd)
            if result.get("status") == "success":
                print("✓")
                success_count += 1
            else:
                print(f"✗ ({result.get('message', 'Unknown error')})")

        return success_count == len(bluetooth_commands)

    def reset_app_preferences(self, serial):
        print(f"\n📱 Resetting app preferences for {serial}...")

        app_commands = [
            ("pm reset-permissions --user 0", "Resetting app permissions"),
            ("cmd package reset-permissions", "Resetting package permissions"),
            (
                "cmd notification reset_assistant_user_set",
                "Resetting notification assistant",
            ),
            ("cmd role reset-roles --user 0", "Resetting app roles"),
            ("pm clear com.android.providers.settings", "Clearing settings provider"),
        ]

        success_count = 0
        for cmd, description in app_commands:
            print(f"  • {description}...", end=" ")
            result = self.client.execute_action(serial, "shell", command=cmd)
            if result.get("status") == "success":
                print("✓")
                success_count += 1
            else:
                print(f"✗ ({result.get('message', 'Unknown error')})")

        return success_count == len(app_commands)

    def reset_location_settings(self, serial):
        print(f"\n📍 Resetting location settings for {serial}...")

        location_commands = [
            ("settings put secure location_providers_allowed -gps", "Disabling GPS"),
            ("settings put secure location_providers_allowed +gps", "Re-enabling GPS"),
        ]

        success_count = 0
        for cmd, description in location_commands:
            print(f"  • {description}...", end=" ")
            result = self.client.execute_action(serial, "shell", command=cmd)
            if result.get("status") == "success":
                print("✓")
                success_count += 1
            else:
                print(f"✗ ({result.get('message', 'Unknown error')})")

        return success_count == len(location_commands)

    def reset_all_settings(self, serial):
        print(f"\n{'=' * 60}")
        print(f"Starting complete reset for device: {serial}")
        print(f"{'=' * 60}")

        results = {
            "Network": self.reset_network_settings(serial),
            "WiFi": self.reset_wifi(serial),
            "Bluetooth": self.reset_bluetooth(serial),
            "App Preferences": self.reset_app_preferences(serial),
            "Location": self.reset_location_settings(serial),
        }

        print(f"\n{'─' * 60}")
        print("RESET SUMMARY:")
        print(f"{'─' * 60}")

        for category, success in results.items():
            status = "✓ Success" if success else "✗ Failed"
            print(f"  {category:20} {status}")

        all_success = all(results.values())

        if all_success:
            print(f"\n✅ All settings successfully reset for {serial}")
        else:
            print(f"\n⚠️  Some settings failed to reset for {serial}")

        return all_success

    def reboot_device(self, serial):
        print(f"\n🔄 Rebooting {serial}...")
        result = self.client.execute_action(serial, "shell", command="reboot")
        if result.get("status") == "success":
            print("✓ Reboot command sent successfully")
            print("⏳ Device will restart. Please wait...")
            return True
        else:
            print(f"✗ Failed to reboot: {result.get('message')}")
            return False

    def run(self, skip_reboot=False):
        if not self.discover_devices():
            return

        total_devices = len(self.devices)
        success_count = 0

        for idx, serial in enumerate(self.devices.keys(), 1):
            if total_devices > 1:
                print(f"\n{'═' * 60}")
                print(f"Processing device {idx}/{total_devices}")
                print(f"{'═' * 60}")

            if self.reset_all_settings(serial):
                success_count += 1

                if not skip_reboot:
                    self.reboot_device(serial)

        print(f"\n{'═' * 60}")
        print("FINAL RESULTS")
        print(f"{'═' * 60}")
        print(f"✓ Successfully reset: {success_count}/{total_devices} device(s)")

        if not skip_reboot and success_count > 0:
            print("✓ Devices are rebooting to apply changes")
        elif skip_reboot and success_count > 0:
            print("⚠️  Manual reboot recommended to fully apply changes")

        print(f"{'═' * 60}\n")


def main():
    skip_reboot = False

    if len(sys.argv) > 1:
        if sys.argv[1] == "--no-reboot":
            skip_reboot = True
        elif sys.argv[1] == "--help":
            print("Usage:")
            print(f"  python {sys.argv[0]}             - Reset all settings and reboot")
            print(
                f"  python {sys.argv[0]} --no-reboot - Reset all settings without reboot"
            )
            print(f"  python {sys.argv[0]} --help      - Show this help")
            return
        else:
            print(f"Unknown option: {sys.argv[1]}")
            print("Use --help for usage information")
            return

    resetter = DeviceSettingsReset()
    resetter.run(skip_reboot=skip_reboot)


if __name__ == "__main__":
    main()
