import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime


class NetworkConfigUndoer:
    """
    A class to undo network configurations on multiple Android devices.
    """

    def __init__(self):
        self.devices = self._get_devices()
        self.lock = threading.Lock()

    def _get_devices(self):
        """
        Retrieves a list of connected device serial numbers.
        """
        try:
            result = subprocess.run(
                ["adb", "devices"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            devices = []
            for line in result.stdout.strip().split("\n")[1:]:
                if "device" in line:
                    serial = line.split("\t")[0]
                    devices.append(serial)
            return devices
        except FileNotFoundError:
            print("❌ ADB not found. Please ensure it is installed and in your PATH.")
            return []
        except Exception as e:
            print(f"❌ Error getting devices: {e}")
            return []

    def undo_network_config(self, serial):
        """
        Executes a series of adb commands to revert network settings for a device.
        """
        print(f"[{serial}] ⏪ Starting network configuration reversal...")

        commands = [
            # Reset proxy settings
            ["settings", "delete", "global", "http_proxy"],
            ["settings", "delete", "global", "global_http_proxy_host"],
            ["settings", "delete", "global", "global_http_proxy_port"],
            ["shell", "su", "-c", "setprop", "net.gprs.http-proxy", "''"],
            ["shell", "su", "-c", "setprop", "net.rmnet0.http-proxy", "''"],
            # Restore captive portal and connectivity checks
            ["shell", "settings", "put", "global", "captive_portal_mode", "1"],
            [
                "shell",
                "settings",
                "put",
                "global",
                "captive_portal_detection_enabled",
                "1",
            ],
            ["shell", "settings", "delete", "global", "connectivity_check_disabled"],
            ["shell", "settings", "delete", "global", "captive_portal_server"],
            # Restore Private DNS mode to automatic
            ["shell", "settings", "put", "global", "private_dns_mode", "opportunistic"],
            # Flush iptables rules
            ["shell", "su", "-c", "iptables", "-F"],
            ["shell", "su", "-c", "iptables", "-t", "nat", "-F"],
            ["shell", "su", "-c", "iptables", "-t", "mangle", "-F"],
            ["shell", "su", "-c", "iptables", "-X"],
            # Restore default iptables policies
            ["shell", "su", "-c", "iptables", "-P", "INPUT", "ACCEPT"],
            ["shell", "su", "-c", "iptables", "-P", "OUTPUT", "ACCEPT"],
            ["shell", "su", "-c", "iptables", "-P", "FORWARD", "ACCEPT"],
            # Re-enable app components that were disabled
            [
                "shell",
                "su",
                "-c",
                "pm",
                "enable",
                "com.zhiliaoapp.musically/com.ss.android.ugc.aweme.net.NetworkStateReceiver",
            ],
            [
                "shell",
                "su",
                "-c",
                "pm",
                "enable",
                "com.zhiliaoapp.musically/com.ss.android.ugc.aweme.net.monitor.NetworkMonitorService",
            ],
            # Restore network interface if it was renamed
            ["shell", "su", "-c", "ip", "link", "set", "rmnet0", "name", "tun0"],
            # Clear network-related app caches
            ["shell", "pm", "clear", "com.android.vending"],
            ["shell", "pm", "clear", "com.google.android.gms"],
            ["shell", "pm", "clear", "com.google.android.gsf"],
        ]

        success_count = 0
        for cmd_args in commands:
            try:
                full_cmd = ["adb", "-s", serial] + cmd_args
                # Hide output unless there is an error
                subprocess.run(
                    full_cmd,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,  # Don't raise exception for non-zero exit codes
                )
                success_count += 1
            except subprocess.TimeoutExpired:
                print(f"[{serial}] ❌ Timeout executing: {' '.join(cmd_args)}")
            except Exception as e:
                print(f"[{serial}] ❌ Error executing {' '.join(cmd_args)}: {e}")

        print(
            f"[{serial}] ✔  Reversal complete. Executed {success_count}/{len(commands)} commands."
        )
        return True

    def undo_all_devices_parallel(self):
        """
        Runs the network undo process on all connected devices in parallel.
        """
        print(f"\n{'='*60}")
        print(f"Reverting network configurations on {len(self.devices)} devices")
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}\n")

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {
                executor.submit(self.undo_network_config, serial): serial
                for serial in self.devices
            }

            results = {}
            for future in as_completed(futures):
                serial = futures[future]
                try:
                    results[serial] = future.result()
                except Exception as e:
                    print(f"[{serial}] ❌ An exception occurred: {e}")
                    results[serial] = False

        successful = sum(1 for success in results.values() if success)
        print(f"\n{'='*60}")
        print(
            f"Reversal process finished: {successful}/{len(self.devices)} devices processed."
        )
        print(f"{'='*60}\n")


def main():
    """
    Main function to initialize and run the network configuration undoer.
    """
    print("╔" + "═" * 58 + "╗")
    print("║" + " Android Network Configuration Reversal Tool".center(58) + "║")
    print("╚" + "═" * 58 + "╝")

    manager = NetworkConfigUndoer()

    if not manager.devices:
        print("\n❌ No devices found. Please connect devices and ensure ADB is working.")
        return

    print(f"\n✔ Found {len(manager.devices)} connected device(s):")
    for device in manager.devices:
        print(f"  • {device}")

    try:
        manager.undo_all_devices_parallel()
        print("\n✅ All operations completed.")
    except KeyboardInterrupt:
        print("\n\n🛑 Process interrupted by user. Exiting.")


if __name__ == "__main__":
    main()
