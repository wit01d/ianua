import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from cache_device_connection import DeviceConnectionClient


class GnirehtetCleaner:
    def __init__(self):
        self.client = DeviceConnectionClient(auto_start_service=True)
        self.devices = self._get_devices()

    def _get_devices(self):
        result = self.client.discover_devices()
        if result.get("status") == "success":
            return result.get("data", {})
        return {}

    def stop_gnirehtet_processes(self, serial):
        try:
            device_info = self.devices.get(serial, {})
            model = device_info.get("model", "Unknown")
            print(f"[{serial}] Stopping gnirehtet processes on {model}...")

            subprocess.run(
                ["adb", "-s", serial, "shell", "am", "force-stop", "com.genymobile.gnirehtet"],
                capture_output=True,
                timeout=5,
            )

            subprocess.run(
                ["adb", "-s", serial, "shell", "am", "stopservice", "com.genymobile.gnirehtet/.GnirehtetService"],
                capture_output=True,
                timeout=5,
            )

            subprocess.run(
                ["adb", "-s", serial, "shell", "su", "-c", "killall", "com.genymobile.gnirehtet"],
                capture_output=True,
                timeout=3,
            )

            print(f"[{serial}] ✔ Stopped gnirehtet processes")
            return True

        except Exception as e:
            print(f"[{serial}] ⚠ Error stopping processes: {e}")
            return False

    def uninstall_gnirehtet(self, serial):
        try:
            device_info = self.devices.get(serial, {})
            model = device_info.get("model", "Unknown")
            print(f"[{serial}] Uninstalling gnirehtet from {model}...")

            result = subprocess.run(
                ["adb", "-s", serial, "shell", "pm", "list", "packages"],
                capture_output=True,
                text=True,
                timeout=5,
            )

            if "com.genymobile.gnirehtet" not in result.stdout:
                print(f"[{serial}] ✔ Gnirehtet not installed on {model}")
                return True

            result = subprocess.run(
                ["adb", "-s", serial, "uninstall", "com.genymobile.gnirehtet"],
                capture_output=True,
                text=True,
                timeout=15,
            )

            if "Success" in result.stdout:
                print(f"[{serial}] ✔ Successfully uninstalled from {model}")
                return True
            else:
                print(f"[{serial}] ❌ Failed to uninstall: {result.stderr}")
                return False

        except Exception as e:
            print(f"[{serial}] ❌ Uninstall error: {e}")
            return False

    def reset_network_settings(self, serial):
        try:
            device_info = self.devices.get(serial, {})
            model = device_info.get("model", "Unknown")
            print(f"[{serial}] Resetting network settings on {model}...")

            subprocess.run(
                ["adb", "-s", serial, "shell", "settings", "put", "global", "captive_portal_mode", "1"],
                capture_output=True,
                timeout=3,
            )

            subprocess.run(
                ["adb", "-s", serial, "shell", "settings", "put", "global", "captive_portal_detection_enabled", "1"],
                capture_output=True,
                timeout=3,
            )

            subprocess.run(
                ["adb", "-s", serial, "shell", "settings", "put", "global", "private_dns_mode", "opportunistic"],
                capture_output=True,
                timeout=3,
            )

            subprocess.run(
                ["adb", "-s", serial, "shell", "settings", "delete", "global", "http_proxy"],
                capture_output=True,
                timeout=3,
            )

            subprocess.run(
                ["adb", "-s", serial, "shell", "su", "-c", "setprop", "net.gprs.http-proxy", "''"],
                capture_output=True,
                timeout=3,
            )

            subprocess.run(
                ["adb", "-s", serial, "shell", "su", "-c", "setprop", "net.rmnet0.http-proxy", "''"],
                capture_output=True,
                timeout=3,
            )

            subprocess.run(
                ["adb", "-s", serial, "shell", "su", "-c", "setprop", "gsm.network.type", "''"],
                capture_output=True,
                timeout=3,
            )

            subprocess.run(
                ["adb", "-s", serial, "shell", "su", "-c", "setprop", "gsm.operator.alpha", "''"],
                capture_output=True,
                timeout=3,
            )

            subprocess.run(
                ["adb", "-s", serial, "shell", "su", "-c", "setprop", "gsm.operator.numeric", "''"],
                capture_output=True,
                timeout=3,
            )

            subprocess.run(
                ["adb", "-s", serial, "shell", "settings", "delete", "global", "captive_portal_server"],
                capture_output=True,
                timeout=3,
            )

            subprocess.run(
                ["adb", "-s", serial, "shell", "settings", "put", "global", "connectivity_check_disabled", "0"],
                capture_output=True,
                timeout=3,
            )

            subprocess.run(
                ["adb", "-s", serial, "shell", "settings", "put", "global", "airplane_mode_on", "0"],
                capture_output=True,
                timeout=3,
            )

            subprocess.run(
                ["adb", "-s", serial, "shell", "su", "-c", "settings", "delete", "global", "preferred_network_mode"],
                capture_output=True,
                timeout=3,
            )

            print(f"[{serial}] ✔ Network settings reset")
            return True

        except Exception as e:
            print(f"[{serial}] ⚠ Error resetting network settings: {e}")
            return False

    def clear_iptables_rules(self, serial):
        try:
            device_info = self.devices.get(serial, {})
            model = device_info.get("model", "Unknown")
            print(f"[{serial}] Clearing iptables rules on {model}...")

            subprocess.run(
                ["adb", "-s", serial, "shell", "su", "-c", "iptables", "-t", "nat", "-D", "OUTPUT", "-p", "udp", "--dport", "53", "-j", "DNAT", "--to-destination", "8.8.8.8:53"],
                capture_output=True,
                timeout=3,
            )

            subprocess.run(
                ["adb", "-s", serial, "shell", "su", "-c", "iptables", "-t", "nat", "-D", "OUTPUT", "-p", "tcp", "--dport", "53", "-j", "DNAT", "--to-destination", "8.8.8.8:53"],
                capture_output=True,
                timeout=3,
            )

            subprocess.run(
                ["adb", "-s", serial, "shell", "su", "-c", "iptables", "-t", "nat", "-F"],
                capture_output=True,
                timeout=3,
            )

            subprocess.run(
                ["adb", "-s", serial, "shell", "su", "-c", "iptables", "-F"],
                capture_output=True,
                timeout=3,
            )

            print(f"[{serial}] ✔ iptables rules cleared")
            return True

        except Exception as e:
            print(f"[{serial}] ⚠ Could not clear iptables (may require root): {e}")
            return False

    def re_enable_app_components(self, serial):
        try:
            device_info = self.devices.get(serial, {})
            model = device_info.get("model", "Unknown")
            print(f"[{serial}] Re-enabling app components on {model}...")

            subprocess.run(
                ["adb", "-s", serial, "shell", "su", "-c", "pm", "enable", "com.zhiliaoapp.musically/com.ss.android.ugc.aweme.net.NetworkStateReceiver"],
                capture_output=True,
                timeout=3,
            )

            subprocess.run(
                ["adb", "-s", serial, "shell", "su", "-c", "pm", "enable", "com.zhiliaoapp.musically/com.ss.android.ugc.aweme.net.monitor.NetworkMonitorService"],
                capture_output=True,
                timeout=3,
            )

            print(f"[{serial}] ✔ App components re-enabled")
            return True

        except Exception as e:
            print(f"[{serial}] ⚠ Could not re-enable app components: {e}")
            return False

    def reset_vpn_trust(self, serial):
        try:
            device_info = self.devices.get(serial, {})
            model = device_info.get("model", "Unknown")
            print(f"[{serial}] Resetting VPN trust settings on {model}...")

            subprocess.run(
                ["adb", "-s", serial, "shell", "settings", "delete", "global", "always_on_vpn_app"],
                capture_output=True,
                timeout=3,
            )

            subprocess.run(
                ["adb", "-s", serial, "shell", "settings", "delete", "global", "always_on_vpn_lockdown"],
                capture_output=True,
                timeout=3,
            )

            subprocess.run(
                ["adb", "-s", serial, "shell", "pm", "clear", "com.android.vpndialogs"],
                capture_output=True,
                timeout=5,
            )

            print(f"[{serial}] ✔ VPN trust settings reset")
            return True

        except Exception as e:
            print(f"[{serial}] ⚠ Error resetting VPN trust: {e}")
            return False

    def clean_device(self, serial):
        try:
            device_info = self.devices.get(serial, {})
            model = device_info.get("model", "Unknown")
            print(f"\n[{serial}] Starting cleanup on {model}...")
            print("-" * 50)

            results = {
                "stop_processes": self.stop_gnirehtet_processes(serial),
                "uninstall": self.uninstall_gnirehtet(serial),
                "reset_network": self.reset_network_settings(serial),
                "clear_iptables": self.clear_iptables_rules(serial),
                "re_enable_components": self.re_enable_app_components(serial),
                "reset_vpn": self.reset_vpn_trust(serial),
            }

            successful = sum(1 for v in results.values() if v)
            total = len(results)

            if successful == total:
                print(f"[{serial}] ✅ Complete cleanup successful on {model}")
            else:
                print(f"[{serial}] ⚠ Partial cleanup: {successful}/{total} tasks completed on {model}")

            return results

        except Exception as e:
            print(f"[{serial}] ❌ Cleanup error: {e}")
            return None

    def clean_all_devices_parallel(self):
        print(f"\n{'='*60}")
        print(f"Cleaning gnirehtet from {len(self.devices)} devices")
        print(f"{'='*60}\n")

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {
                executor.submit(self.clean_device, serial): serial
                for serial in self.devices
            }

            all_results = {}
            for future in as_completed(futures):
                serial = futures[future]
                try:
                    all_results[serial] = future.result()
                except Exception as e:
                    print(f"[{serial}] ❌ Cleanup exception: {e}")
                    all_results[serial] = None

        fully_successful = sum(
            1
            for results in all_results.values()
            if results and all(results.values())
        )

        print(f"\n{'='*60}")
        print(f"Cleanup Summary:")
        print(f"  ✅ Fully cleaned: {fully_successful}/{len(self.devices)} devices")

        for serial, results in all_results.items():
            if results and not all(results.values()):
                failed_tasks = [k for k, v in results.items() if not v]
                model = self.devices[serial].get("model", "Unknown")
                print(f"  ⚠ {serial} ({model}): Failed tasks: {', '.join(failed_tasks)}")

        print(f"{'='*60}\n")

        return all_results

    def kill_relay_server(self):
        try:
            print("\n🛑 Stopping gnirehtet relay server...")

            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/IM", "java.exe"], capture_output=True)
                subprocess.run(["taskkill", "/F", "/IM", "gnirehtet.exe"], capture_output=True)
            else:
                result = subprocess.run(["lsof", "-t", "-i:31416"], capture_output=True, text=True)
                if result.stdout.strip():
                    pid = result.stdout.strip()
                    subprocess.run(["kill", "-9", pid], capture_output=True)
                    print(f"✔ Killed relay server (PID: {pid})")

                subprocess.run(["pkill", "-f", "gnirehtet"], capture_output=True)

            print("✔ Relay server processes terminated")
            return True

        except Exception as e:
            print(f"⚠ Could not kill relay server: {e}")
            return False


def main():
    import os

    print("╔" + "═" * 58 + "╗")
    print("║" + " Gnirehtet Complete Cleanup Tool".center(58) + "║")
    print("╚" + "═" * 58 + "╝")
    print("\n⚠ This will remove ALL gnirehtet components and reset network settings")

    cleaner = GnirehtetCleaner()

    if not cleaner.devices:
        print("\n❌ No devices found. Please connect devices and try again.")
        return

    print(f"\n✔ Found {len(cleaner.devices)} connected device(s)")
    for serial, device_info in cleaner.devices.items():
        print(f"  • {serial}: {device_info.get('model', 'Unknown')}")

    input("\nPress Enter to start cleanup or Ctrl+C to cancel...")

    cleaner.kill_relay_server()

    cleaner.clean_all_devices_parallel()

    print("\n✅ Cleanup complete!")
    print("All gnirehtet components have been removed and settings reset.")
    print("\nNote: Some settings may require a device reboot to fully take effect.")


if __name__ == "__main__":
    main()
