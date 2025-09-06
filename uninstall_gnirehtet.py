import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed


class GnirehtetUninstaller:
    """
    A class to manage the uninstallation of Gnirehtet from multiple Android devices.
    """

    def __init__(self, gnirehtet_dir=None):
        """
        Initializes the uninstaller, locating the Gnirehtet directory.
        """
        if gnirehtet_dir is None:
            # Assume the 'gnirehtet' directory is in the same folder as the script
            script_dir = os.path.dirname(os.path.abspath(__file__))
            gnirehtet_dir = os.path.join(script_dir, "gnirehtet")

        self.gnirehtet_dir = os.path.abspath(gnirehtet_dir)
        print(f"📁 Using gnirehtet directory for cleanup: {self.gnirehtet_dir}")

    def get_connected_devices(self):
        """
        Retrieves a list of serial numbers for all connected ADB devices.
        """
        try:
            result = subprocess.run(
                ["adb", "devices"],
                capture_output=True,
                text=True,
                timeout=5,
                check=True
            )
            devices = []
            lines = result.stdout.strip().split('\n')
            for line in lines[1:]:  # Skip the "List of devices attached" header
                if "device" in line:
                    serial = line.split('\t')[0]
                    devices.append(serial)
            return devices
        except FileNotFoundError:
            print("❌ ADB not found. Please ensure it is installed and in your system's PATH.")
            return []
        except subprocess.CalledProcessError as e:
            print(f"❌ Error executing 'adb devices': {e.stderr}")
            return []
        except Exception as e:
            print(f"❌ An unexpected error occurred while finding devices: {e}")
            return []

    def stop_client_on_device(self, serial):
        """
        Stops the Gnirehtet client process for a specific device.
        """
        print(f"[{serial}] Stopping gnirehtet client...")
        try:
            # Determine the correct command based on the operating system
            if os.name == "nt":
                cmd_path = os.path.join(self.gnirehtet_dir, "gnirehtet.cmd")
                if os.path.exists(cmd_path):
                    cmd = ["cmd", "/c", cmd_path, "stop", serial]
                else:
                    cmd = ["java", "-jar", os.path.join(self.gnirehtet_dir, "gnirehtet.jar"), "stop", serial]
            else:
                bin_path = os.path.join(self.gnirehtet_dir, "gnirehtet")
                if os.path.exists(bin_path):
                    cmd = [bin_path, "stop", serial]
                else:
                    cmd = ["java", "-jar", os.path.join(self.gnirehtet_dir, "gnirehtet.jar"), "stop", serial]

            subprocess.run(cmd, cwd=self.gnirehtet_dir, capture_output=True, timeout=10)
            print(f"[{serial}] ✔ Client stop command issued.")
            return True
        except FileNotFoundError:
            print(f"[{serial}] ⚠ Could not find gnirehtet executable/jar to stop the client. Skipping.")
            return False
        except Exception as e:
            print(f"[{serial}] ⚠ Error stopping client: {e}")
            return False

    def revert_network_settings(self, serial):
        """
        Reverts common network settings that may have been changed by Gnirehtet.
        """
        print(f"[{serial}] Reverting network settings to default...")
        try:
            # Remove any http_proxy setting
            subprocess.run(
                ["adb", "-s", serial, "shell", "settings", "delete", "global", "http_proxy"],
                capture_output=True, timeout=5
            )
            # Re-enable captive portal detection
            subprocess.run(
                ["adb", "-s", serial, "shell", "settings", "put", "global", "captive_portal_mode", "1"],
                capture_output=True, timeout=5
            )
            # Re-enable WiFi (a safe default)
            subprocess.run(
                ["adb", "-s", serial, "shell", "svc", "wifi", "enable"],
                capture_output=True, timeout=5
            )
            # Ensure mobile data is off
            subprocess.run(
                ["adb", "-s", serial, "shell", "svc", "data", "disable"],
                capture_output=True, timeout=5
            )
            print(f"[{serial}] ✔ Network settings reverted.")
            return True
        except Exception as e:
            print(f"[{serial}] ⚠ Could not revert all network settings: {e}")
            return False

    def uninstall_apk_from_device(self, serial):
        """
        Uninstalls the Gnirehtet APK from a specific device.
        """
        print(f"[{serial}] Uninstalling Gnirehtet APK...")
        try:
            result = subprocess.run(
                ["adb", "-s", serial, "uninstall", "com.genymobile.gnirehtet"],
                capture_output=True,
                text=True,
                timeout=20,
            )
            if "Success" in result.stdout:
                print(f"[{serial}] ✔ Successfully uninstalled APK.")
                return True
            elif "not found" in result.stderr:
                print(f"[{serial}] ✔ APK was not installed.")
                return True
            else:
                print(f"[{serial}] ❌ Failed to uninstall APK: {result.stderr.strip()}")
                return False
        except Exception as e:
            print(f"[{serial}] ❌ Error during uninstallation: {e}")
            return False

    def cleanup_device(self, serial):
        """
        Runs the full cleanup process for a single device.
        """
        print(f"\n--- Starting cleanup for device: {serial} ---")
        self.stop_client_on_device(serial)
        apk_uninstalled = self.uninstall_apk_from_device(serial)
        self.revert_network_settings(serial)
        print(f"--- Cleanup for {serial} finished ---")
        return apk_uninstalled

    def cleanup_all_devices(self):
        """
        Finds all connected devices and runs the cleanup process in parallel.
        """
        devices = self.get_connected_devices()
        if not devices:
            print("\nNo devices found to clean up.")
            return

        print(f"\nFound {len(devices)} device(s): {', '.join(devices)}")
        print("Starting uninstallation process on all devices...\n")

        successful_uninstalls = 0
        with ThreadPoolExecutor(max_workers=10) as executor:
            # Create a future for each device cleanup
            future_to_device = {executor.submit(self.cleanup_device, serial): serial for serial in devices}

            for future in as_completed(future_to_device):
                serial = future_to_device[future]
                try:
                    # The result is True if APK uninstallation was successful
                    if future.result():
                        successful_uninstalls += 1
                except Exception as e:
                    print(f"❌ An exception occurred while cleaning up {serial}: {e}")

        print("\n" + "="*50)
        print("✅ Cleanup Summary ✅")
        print(f"   Successfully cleaned up {successful_uninstalls}/{len(devices)} devices.")
        print("="*50)


def main():
    """
    Main function to execute the script.
    """
    print("╔" + "═" * 58 + "╗")
    print("║" + " Gnirehtet Uninstaller".center(58) + "║")
    print("╚" + "═" * 58 + "╝")

    # Allows specifying a custom gnirehtet directory via command line argument
    gnirehtet_dir = sys.argv[1] if len(sys.argv) > 1 else None

    uninstaller = GnirehtetUninstaller(gnirehtet_dir)

    try:
        uninstaller.cleanup_all_devices()
    except KeyboardInterrupt:
        print("\n\n🛑 Process interrupted by user. Exiting.")
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}")


if __name__ == "__main__":
    main()
