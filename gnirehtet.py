import os
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from cache_device_connection import DeviceConnectionClient


class GnirehtetManager:
    def __init__(self, gnirehtet_dir=None):
        if gnirehtet_dir is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            gnirehtet_dir = os.path.join(script_dir, "gnirehtet")

        self.gnirehtet_dir = os.path.abspath(gnirehtet_dir)
        self.gnirehtet_bin = os.path.join(self.gnirehtet_dir, "gnirehtet")
        self.gnirehtet_jar = os.path.join(self.gnirehtet_dir, "gnirehtet.jar")
        self.gnirehtet_apk = os.path.join(self.gnirehtet_dir, "gnirehtet.apk")

        print(f"📁 Using gnirehtet directory: {self.gnirehtet_dir}")

        self.client = DeviceConnectionClient(auto_start_service=True)
        self.devices = self._get_devices()
        self.relay_process = None
        self.device_processes = {}
        self.lock = threading.Lock()
        self.initial_setup_time = None
        self.device_last_restart = {}
        self.device_connection_status = {}
        self.monitoring_enabled = False

    def _get_devices(self):
        result = self.client.discover_devices()
        if result.get("status") == "success":
            return result.get("data", {})
        return {}

    def check_prerequisites(self):
        print(f"\n🔍 Checking prerequisites...")
        print(f"   Looking for files in: {self.gnirehtet_dir}")

        if not os.path.exists(self.gnirehtet_dir):
            print(f"❌ Directory does not exist: {self.gnirehtet_dir}")
            return False

        if not os.path.exists(self.gnirehtet_apk):
            print(f"❌ APK not found at: {self.gnirehtet_apk}")
            print(f"   Files in directory:")
            try:
                for file in os.listdir(self.gnirehtet_dir):
                    print(f"     - {file}")
            except:
                print(f"     Could not list directory contents")
            return False
        else:
            print(f"✔ APK found: {self.gnirehtet_apk}")

        if os.name != "nt":
            if not os.path.exists(self.gnirehtet_bin):
                if os.path.exists(self.gnirehtet_jar):
                    print(f"✔ Will use JAR file: {self.gnirehtet_jar}")
                else:
                    print(f"❌ Neither binary nor JAR found")
                    return False
            else:
                print(f"✔ Binary found: {self.gnirehtet_bin}")
                if not os.access(self.gnirehtet_bin, os.X_OK):
                    print(f"   Making {self.gnirehtet_bin} executable...")
                    os.chmod(self.gnirehtet_bin, 0o755)

        print(f"✔ All prerequisites satisfied\n")
        return True

    def check_apk_installed(self, serial):
        try:
            result = subprocess.run(
                ["adb", "-s", serial, "shell", "pm", "list", "packages"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return "com.genymobile.gnirehtet" in result.stdout
        except Exception as e:
            print(f"Error checking APK on {serial}: {e}")
            return False

    def install_apk_on_device(self, serial):
        try:
            device_info = self.devices.get(serial, {})
            model = device_info.get("model", "Unknown")

            print(f"[{serial}] Checking if gnirehtet is already installed...")

            if self.check_apk_installed(serial):
                print(f"[{serial}] ✔ Gnirehtet already installed on {model}")
                return True

            print(f"[{serial}] Installing gnirehtet on {model}...")

            result = subprocess.run(
                ["adb", "-s", serial, "install", "-r", self.gnirehtet_apk],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if "Success" in result.stdout or self.check_apk_installed(serial):
                print(f"[{serial}] ✔ Successfully installed on {model}")
                return True
            else:
                print(f"[{serial}] ❌ Failed to install: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            print(f"[{serial}] ❌ Installation timeout")
            return False
        except Exception as e:
            print(f"[{serial}] ❌ Installation error: {e}")
            return False

    def is_port_in_use(self, port=31416):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(("127.0.0.1", port))
        sock.close()
        return result == 0

    def kill_existing_relay(self):
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/IM", "java.exe"], capture_output=True
                )
            else:
                result = subprocess.run(
                    ["lsof", "-t", "-i:31416"], capture_output=True, text=True
                )
                if result.stdout.strip():
                    pid = result.stdout.strip()
                    subprocess.run(["kill", "-9", pid], capture_output=True)
                    time.sleep(1)
                    print(f"✔ Killed existing relay process (PID: {pid})")
        except Exception as e:
            print(f"⚠ Could not kill existing relay: {e}")

    def start_relay_server(self):
        if self.is_port_in_use():
            print("✔ Using existing relay server on port 31416")
            return True

        print("Starting new gnirehtet relay server...")

        if os.name == "nt":
            if os.path.exists(os.path.join(self.gnirehtet_dir, "gnirehtet.cmd")):
                cmd = [
                    "cmd",
                    "/c",
                    os.path.join(self.gnirehtet_dir, "gnirehtet.cmd"),
                    "relay",
                ]
            else:
                cmd = ["java", "-jar", self.gnirehtet_jar, "relay"]
        else:
            if os.path.exists(self.gnirehtet_bin):
                cmd = [self.gnirehtet_bin, "relay"]
            else:
                cmd = ["java", "-jar", self.gnirehtet_jar, "relay"]

        try:
            self.relay_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.gnirehtet_dir,
            )

            time.sleep(2)

            if self.relay_process.poll() is None:
                print("✔ Relay server started successfully (port 31416)")
                return True
            else:
                stdout, stderr = self.relay_process.communicate(timeout=1)
                if "Address already in use" in stderr.decode():
                    print("✔ Relay server already running, will use existing instance")
                    return True
                else:
                    print(f"❌ Relay server failed to start: {stderr.decode()}")
                    return False

        except Exception as e:
            print(f"❌ Error starting relay server: {e}")
            return False

    def stop_relay_server(self):
        if self.relay_process and self.relay_process.poll() is None:
            print("Stopping relay server...")
            self.relay_process.terminate()
            try:
                self.relay_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.relay_process.kill()
                self.relay_process.wait()
            print("✔ Relay server stopped")
            self.relay_process = None

    def configure_network_for_device(self, serial):
        try:
            device_info = self.devices.get(serial, {})
            model = device_info.get("model", "Unknown")

            print(f"[{serial}] Configuring network for {model}...")

            subprocess.run(
                [
                    "adb",
                    "-s",
                    serial,
                    "shell",
                    "settings",
                    "put",
                    "global",
                    "captive_portal_mode",
                    "0",
                ],
                capture_output=True,
                timeout=3,
            )
            subprocess.run(
                [
                    "adb",
                    "-s",
                    serial,
                    "shell",
                    "settings",
                    "put",
                    "global",
                    "captive_portal_detection_enabled",
                    "0",
                ],
                capture_output=True,
                timeout=3,
            )
            subprocess.run(
                [
                    "adb",
                    "-s",
                    serial,
                    "shell",
                    "settings",
                    "put",
                    "global",
                    "private_dns_mode",
                    "off",
                ],
                capture_output=True,
                timeout=3,
            )

            subprocess.run(
                [
                    "adb",
                    "-s",
                    serial,
                    "shell",
                    "svc",
                    "wifi",
                    "disable",
                ],
                capture_output=True,
                timeout=3,
            )
            subprocess.run(
                [
                    "adb",
                    "-s",
                    serial,
                    "shell",
                    "svc",
                    "data",
                    "disable",
                ],
                capture_output=True,
                timeout=3,
            )

            print(f"[{serial}] ✔ Network configured for {model}")
            return True

        except Exception as e:
            print(f"[{serial}] ❌ Error configuring network: {e}")
            return False

    def launch_vpn_accepter(self):
        try:
            vpn_script = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "vpn_config.py"
            )
            if os.path.exists(vpn_script):
                print("\n🤖 Launching VPN auto-accepter in background...")
                subprocess.Popen(
                    [sys.executable, vpn_script],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                print("✔ VPN auto-accepter started")
                return True
            else:
                print("⚠ vpn_config.py not found, please accept VPN dialogs manually")
                return False
        except Exception as e:
            print(f"⚠ Could not launch VPN accepter: {e}")
            print("  Please run vpn_config.py manually in another terminal")
            return False

    def start_client_on_device(self, serial):
        try:
            device_info = self.devices.get(serial, {})
            model = device_info.get("model", "Unknown")

            if serial in self.device_processes:
                if self.device_processes[serial].poll() is None:
                    print(f"[{serial}] ⚠ Client already running for {model}")
                    return True

            print(f"[{serial}] Starting gnirehtet client for {model}...")

            if os.name == "nt":
                if os.path.exists(os.path.join(self.gnirehtet_dir, "gnirehtet.cmd")):
                    cmd = [
                        "cmd",
                        "/c",
                        os.path.join(self.gnirehtet_dir, "gnirehtet.cmd"),
                        "start",
                        serial,
                    ]
                else:
                    cmd = ["java", "-jar", self.gnirehtet_jar, "start", serial]
            else:
                if os.path.exists(self.gnirehtet_bin):
                    cmd = [self.gnirehtet_bin, "start", serial]
                else:
                    cmd = ["java", "-jar", self.gnirehtet_jar, "start", serial]

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.gnirehtet_dir,
            )

            with self.lock:
                self.device_processes[serial] = process

            time.sleep(1)

            stdout, stderr = process.communicate(timeout=2)

            if (
                "Reverse tethering started" in stdout.decode()
                or "started" in stdout.decode().lower()
            ):
                print(f"[{serial}] ✔ Client started successfully for {model}")
                return True
            else:
                print(f"[{serial}] ✔ Client command executed for {model}")
                return True

        except subprocess.TimeoutExpired:
            print(f"[{serial}] ✔ Client process started for {model}")
            return True
        except Exception as e:
            print(f"[{serial}] ❌ Error starting client: {e}")
            return False

    def stop_client_on_device(self, serial):
        try:
            print(f"[{serial}] Stopping gnirehtet client...")

            if os.name == "nt":
                if os.path.exists(os.path.join(self.gnirehtet_dir, "gnirehtet.cmd")):
                    cmd = [
                        "cmd",
                        "/c",
                        os.path.join(self.gnirehtet_dir, "gnirehtet.cmd"),
                        "stop",
                        serial,
                    ]
                else:
                    cmd = ["java", "-jar", self.gnirehtet_jar, "stop", serial]
            else:
                if os.path.exists(self.gnirehtet_bin):
                    cmd = [self.gnirehtet_bin, "stop", serial]
                else:
                    cmd = ["java", "-jar", self.gnirehtet_jar, "stop", serial]

            subprocess.run(cmd, cwd=self.gnirehtet_dir, capture_output=True, timeout=5)

            with self.lock:
                if serial in self.device_processes:
                    process = self.device_processes[serial]
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
                    del self.device_processes[serial]

            print(f"[{serial}] ✔ Client stopped")

        except Exception as e:
            print(f"[{serial}] ⚠ Error stopping client: {e}")

    def install_all_parallel(self):
        print(f"\n{'='*60}")
        print(f"Installing gnirehtet APK on {len(self.devices)} devices")
        print(f"{'='*60}\n")

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {
                executor.submit(self.install_apk_on_device, serial): serial
                for serial in self.devices
            }

            results = {}
            for future in as_completed(futures):
                serial = futures[future]
                try:
                    results[serial] = future.result()
                except Exception as e:
                    print(f"[{serial}] ❌ Installation exception: {e}")
                    results[serial] = False

        successful = sum(1 for success in results.values() if success)
        print(f"\n{'='*60}")
        print(f"Installation complete: {successful}/{len(self.devices)} successful")
        print(f"{'='*60}\n")

        return results

    def configure_all_networks_parallel(self):
        print(f"\n{'='*60}")
        print(f"Configuring network on {len(self.devices)} devices")
        print(f"{'='*60}\n")

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {
                executor.submit(self.configure_network_for_device, serial): serial
                for serial in self.devices
            }

            results = {}
            for future in as_completed(futures):
                serial = futures[future]
                try:
                    results[serial] = future.result()
                except Exception as e:
                    print(f"[{serial}] ⚠ Configuration exception: {e}")
                    results[serial] = False

        successful = sum(1 for success in results.values() if success)
        print(f"\n{'='*60}")
        print(
            f"Network configuration complete: {successful}/{len(self.devices)} successful"
        )
        print(f"{'='*60}\n")

        return results

    def start_all_clients_parallel(self):
        print(f"\n{'='*60}")
        print(f"Starting gnirehtet clients on {len(self.devices)} devices")
        print(f"{'='*60}\n")

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {
                executor.submit(self.start_client_on_device, serial): serial
                for serial in self.devices
            }

            results = {}
            for future in as_completed(futures):
                serial = futures[future]
                try:
                    results[serial] = future.result()
                except Exception as e:
                    print(f"[{serial}] ❌ Start exception: {e}")
                    results[serial] = False

        successful = sum(1 for success in results.values() if success)
        print(f"\n{'='*60}")
        print(f"Gnirehtet clients started on {successful}/{len(self.devices)} devices")
        print(f"{'='*60}\n")

        return results

    def stop_all(self):
        print(f"\n{'='*60}")
        print(f"Stopping gnirehtet on all devices")
        print(f"{'='*60}\n")

        for serial in list(self.device_processes.keys()):
            self.stop_client_on_device(serial)

        self.stop_relay_server()

        print(f"✔ All gnirehtet processes stopped\n")

    def check_vpn_status(self, serial):
        try:
            result = subprocess.run(
                ["adb", "-s", serial, "shell", "dumpsys", "connectivity"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if "VPN:" in result.stdout and "CONNECTED" in result.stdout:
                return True

            result = subprocess.run(
                ["adb", "-s", serial, "shell", "ip", "addr", "show", "tun0"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if "inet " in result.stdout:
                return True

            return False

        except:
            return False

    def check_connectivity(self, serial, verbose=False):
        try:
            result = subprocess.run(
                ["adb", "-s", serial, "shell", "dumpsys", "connectivity"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if "VPN:" in result.stdout and "CONNECTED" in result.stdout:
                return True

            result = subprocess.run(
                ["adb", "-s", serial, "shell", "ip", "addr", "show", "tun0"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if "inet " in result.stdout:
                return True

            if verbose:
                result = subprocess.run(
                    [
                        "adb",
                        "-s",
                        serial,
                        "shell",
                        "ping",
                        "-c",
                        "1",
                        "-W",
                        "2",
                        "8.8.8.8",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if "1 received" in result.stdout or "time=" in result.stdout:
                    return True

            return False

        except:
            return False

    def monitor_status(self, detailed=True):
        print("\n📊 Current Status:")
        print(f"{'Serial':<20} {'Model':<20} {'Installed':<12} {'VPN Status':<12}")
        print("-" * 64)

        connected_count = 0
        for serial, device_info in self.devices.items():
            model = device_info.get("model", "Unknown")[:19]
            installed = "✔" if self.check_apk_installed(serial) else "✗"
            vpn_status = "✔" if self.check_vpn_status(serial) else "✗"

            if vpn_status == "✔":
                connected_count += 1

            print(f"{serial:<20} {model:<20} {installed:<12} {vpn_status:<12}")

        if self.is_port_in_use():
            relay_status = "✔ Running"
        else:
            relay_status = "✗ Stopped"

        print(f"\nRelay Server: {relay_status}")
        print(f"Devices with VPN: {connected_count}/{len(self.devices)}")

        if not self.monitoring_enabled:
            print("Auto-monitoring: Disabled (connections will remain stable)")
        else:
            print("Auto-monitoring: Enabled")

    def run_full_setup(self, enable_monitoring=False):
        self.monitoring_enabled = enable_monitoring

        if not self.check_prerequisites():
            return False

        print(f"\n🚀 Starting full gnirehtet setup for {len(self.devices)} devices")
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Auto-monitoring: {'Enabled' if enable_monitoring else 'Disabled'}\n")

        for serial, device_info in self.devices.items():
            print(f"  • {serial}: {device_info.get('model', 'Unknown')}")

        install_results = self.install_all_parallel()

        if not any(install_results.values()):
            print("\n❌ No installations succeeded, aborting")
            return False

        if not self.start_relay_server():
            print("\n❌ Failed to start relay server, aborting")
            return False

        time.sleep(2)

        configure_results = self.configure_all_networks_parallel()

        start_results = self.start_all_clients_parallel()

        self.initial_setup_time = time.time()

        self.launch_vpn_accepter()

        print("\n⚠ VPN dialogs will appear on devices")
        print("  The VPN auto-accepter is running in the background")
        print("  It will automatically accept VPN requests for 60 seconds\n")

        time.sleep(5)

        self.monitor_status()

        return True

    def check_and_display_status(self):
        connected_count = sum(1 for s in self.devices if self.check_vpn_status(s))
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] VPN Status: {connected_count}/{len(self.devices)} devices connected"
        )

        disconnected = [s for s in self.devices if not self.check_vpn_status(s)]
        if disconnected and len(disconnected) <= 5:
            for serial in disconnected:
                model = self.devices[serial].get("model", "Unknown")
                print(f"  ⚠ {serial} ({model}) - VPN not detected")


def main():
    print("╔" + "═" * 58 + "╗")
    print("║" + " Gnirehtet Multi-Device Manager".center(58) + "║")
    print("╚" + "═" * 58 + "╝")

    gnirehtet_dir = None
    enable_monitoring = False

    for arg in sys.argv[1:]:
        if arg in ["--monitor", "-m"]:
            enable_monitoring = True
        elif not gnirehtet_dir:
            gnirehtet_dir = arg

    if gnirehtet_dir:
        print(f"\n📁 Using custom gnirehtet directory: {gnirehtet_dir}")

    if enable_monitoring:
        print("⚠ Auto-monitoring enabled (use with caution)")

    manager = GnirehtetManager(gnirehtet_dir)

    if not manager.devices:
        print("\n❌ No devices found. Please connect devices and try again.")
        return

    print(f"\n✔ Found {len(manager.devices)} connected device(s)")

    try:
        success = manager.run_full_setup(enable_monitoring=enable_monitoring)

        if success:
            print("\n✅ Setup completed successfully!")
            print("Press Ctrl+C to stop all gnirehtet instances and exit")

            if not enable_monitoring:
                print("\n🔒 Connections established - no automatic monitoring")
                print("The VPN connections will remain stable without intervention")

                while True:
                    time.sleep(30)
                    manager.check_and_display_status()
            else:
                print("\n⚠ Monitoring mode enabled - connections may be restarted")

                check_counter = 0
                while True:
                    time.sleep(10)
                    check_counter += 1

                    if check_counter % 6 == 0:
                        manager.check_and_display_status()

                    if check_counter % 30 == 0:
                        check_counter = 0

    except KeyboardInterrupt:
        print("\n\n🛑 Shutting down...")
        manager.stop_all()
        print("✔ Cleanup complete")


if __name__ == "__main__":
    main()
