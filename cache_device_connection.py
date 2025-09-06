import base64
import io
import json
import os
import pickle
import socket
import struct
import subprocess
import sys
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
from datetime import datetime, timedelta

import uiautomator2 as u2
from PIL import Image


class PersistentDeviceConnection:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "initialized"):
            self.devices = {}
            self.executor = ThreadPoolExecutor(max_workers=10)

            cache_dir = "cache"
            if not os.path.exists(cache_dir):
                os.makedirs(cache_dir)
            self.connection_cache_file = os.path.join(cache_dir, "/connections_cache.pkl")

            self.max_connection_age = timedelta(minutes=30)
            self.initialized = True
            self._start_keepalive_thread()

    def _start_keepalive_thread(self):
        def keepalive_worker():
            while True:
                time.sleep(30)
                self._send_keepalive_all()

        thread = threading.Thread(target=keepalive_worker, daemon=True)
        thread.start()

    def _send_keepalive_all(self):
        for serial, device_data in list(self.devices.items()):
            try:
                if device_data and device_data.get("device"):
                    device_data["device"].shell("echo keepalive", timeout=2)
            except:
                pass

    def _is_connection_healthy(self, serial):
        if serial not in self.devices:
            return False

        device_data = self.devices[serial]
        if not device_data or not device_data.get("device"):
            return False

        try:
            device_data["device"].shell("echo health_check", timeout=2)
            device_data["last_health_check"] = datetime.now()
            return True
        except:
            return False

    def get_connected_devices(self):
        try:
            result = subprocess.run(
                ["adb", "devices"], capture_output=True, text=True, timeout=5
            )
            lines = result.stdout.strip().split("\n")[1:]
            devices = []
            for line in lines:
                if "\t" in line and "device" in line:
                    serial = line.split("\t")[0]
                    devices.append(serial)
            return devices
        except Exception as e:
            print(f"Error getting devices: {e}")
            return []

    def connect_single_device(self, serial, force_reconnect=False):
        if not force_reconnect and serial in self.devices:
            if self._is_connection_healthy(serial):
                print(f"✔ Reusing existing connection to {serial}")
                return serial, self.devices[serial]
            else:
                print(f"Connection to {serial} unhealthy, reconnecting...")
                del self.devices[serial]

        try:
            print(f"Establishing new connection to {serial}...")
            device = u2.connect_usb(serial)
            device.implicitly_wait(1.0)

            device_info = device.device_info
            print(f"✔ Connected to: {serial} - {device_info.get('model', 'Unknown')}")

            device_data = {
                "device": device,
                "info": device_info,
                "history": deque(maxlen=50),
                "last_hierarchy": None,
                "last_hierarchy_time": 0,
                "connected_at": datetime.now(),
                "last_health_check": datetime.now(),
            }

            self.devices[serial] = device_data
            return serial, device_data
        except Exception as e:
            print(f"✗ Failed to connect to {serial}: {str(e)}")
            return serial, None

    def discover_devices(self, force_reconnect=False):
        device_serials = self.get_connected_devices()
        if not device_serials:
            print("No Android devices found")
            return {}

        print(f"Found {len(device_serials)} devices")

        if force_reconnect:
            self.devices.clear()

        existing_serials = set(self.devices.keys())
        new_serials = set(device_serials)

        to_remove = existing_serials - new_serials
        for serial in to_remove:
            print(f"Removing disconnected device: {serial}")
            del self.devices[serial]

        futures = []
        for serial in device_serials:
            future = self.executor.submit(
                self.connect_single_device, serial, force_reconnect
            )
            futures.append(future)

        for future in as_completed(futures):
            try:
                serial, device_data = future.result(timeout=30)
            except TimeoutError:
                print(f"Timeout connecting to device")
            except Exception as e:
                print(f"Error processing device: {e}")

        return {k: v for k, v in self.devices.items() if v is not None}

    def get_device(self, serial):
        if self._is_connection_healthy(serial):
            return self.devices[serial]

        _, device_data = self.connect_single_device(serial, force_reconnect=True)
        return device_data

    def close_all_connections(self):
        for serial in list(self.devices.keys()):
            try:
                if self.devices[serial] and self.devices[serial].get("device"):
                    self.devices[serial]["device"].uiautomator.stop()
            except:
                pass
            del self.devices[serial]

    def __del__(self):
        if hasattr(self, "executor"):
            self.executor.shutdown(wait=False)


class DeviceConnectionService:
    def __init__(self, host="localhost", port=9999):
        self.host = host
        self.port = port
        self.connection_manager = PersistentDeviceConnection()
        self.server_socket = None
        self.running = False

    def start(self):
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)
            self.running = True

            print(f"╔════════════════════════════════════════════╗")
            print(f"║  Device Connection Service Started         ║")
            print(f"║  Host: {self.host:<20}                ║")
            print(f"║  Port: {self.port:<20}                ║")
            print(f"╚════════════════════════════════════════════╝")
            print(f"\nWaiting for client connections...\n")

            while self.running:
                try:
                    client_socket, address = self.server_socket.accept()
                    print(
                        f"[{datetime.now().strftime('%H:%M:%S')}] Client connected from {address}"
                    )
                    thread = threading.Thread(
                        target=self._handle_client, args=(client_socket,)
                    )
                    thread.daemon = True
                    thread.start()
                except:
                    break
        except OSError as e:
            if "Address already in use" in str(e):
                print(f"\n✗ ERROR: Port {self.port} is already in use!")
                print(f"  Another server instance is already running.")
                print(f"  To stop it: pkill -f 'device_connection_service.py'")
                self.running = False
            else:
                print(f"\n✗ ERROR starting server: {e}")
                self.running = False

    def _recv_all(self, sock, size):
        data = b""
        while len(data) < size:
            chunk = sock.recv(min(size - len(data), 8192))
            if not chunk:
                raise ConnectionError("Connection closed")
            data += chunk
        return data

    def _send_data(self, sock, data):
        serialized = pickle.dumps(data)
        size = struct.pack("!I", len(serialized))
        sock.sendall(size + serialized)

    def _recv_data(self, sock):
        size_data = self._recv_all(sock, 4)
        size = struct.unpack("!I", size_data)[0]
        data = self._recv_all(sock, size)
        return pickle.loads(data)

    def _handle_client(self, client_socket):
        try:
            request = self._recv_data(client_socket)

            command = request.get("command")
            response = {"status": "error", "data": None}

            if command == "discover":
                force = request.get("force_reconnect", False)
                devices = self.connection_manager.discover_devices(force)
                device_info = {}
                for serial, data in devices.items():
                    device_info[serial] = {
                        "model": data["info"].get("model", "Unknown"),
                        "connected_at": data["connected_at"].isoformat(),
                        "healthy": True,
                    }
                response = {"status": "success", "data": device_info}

            elif command == "batch_execute":
                actions = request.get("actions", [])
                results = []

                for action_data in actions:
                    serial = action_data.get("serial")
                    action = action_data.get("action")
                    params = action_data.get("params", {})

                    try:
                        device_data = self.connection_manager.get_device(serial)
                        if device_data:
                            device = device_data["device"]

                            if action == "shell":
                                cmd = params.pop("command", None)
                                if cmd:
                                    result = device.shell(cmd, **params)
                                else:
                                    result = device.shell(**params)
                                results.append(
                                    {
                                        "serial": serial,
                                        "status": "success",
                                        "data": result,
                                    }
                                )
                            elif action == "click":
                                device.click(**params)
                                results.append({"serial": serial, "status": "success"})
                            elif action == "swipe":
                                device.swipe(**params)
                                results.append({"serial": serial, "status": "success"})
                            elif action == "text":
                                device.set_text(**params)
                                results.append({"serial": serial, "status": "success"})
                            elif action == "app_start":
                                device.app_start(**params)
                                results.append({"serial": serial, "status": "success"})
                            else:
                                results.append(
                                    {
                                        "serial": serial,
                                        "status": "error",
                                        "message": f"Unknown action: {action}",
                                    }
                                )
                        else:
                            results.append(
                                {
                                    "serial": serial,
                                    "status": "error",
                                    "message": "Device not connected",
                                }
                            )
                    except Exception as e:
                        results.append(
                            {"serial": serial, "status": "error", "message": str(e)}
                        )

                response = {"status": "success", "data": results}

            elif command == "get_device":
                serial = request.get("serial")
                if serial:
                    device_data = self.connection_manager.get_device(serial)
                    if device_data:
                        response = {
                            "status": "success",
                            "data": {
                                "model": device_data["info"].get("model"),
                                "connected": True,
                            },
                        }

            elif command == "dump_hierarchy":
                serial = request.get("serial")
                compressed = request.get("compressed", False)
                pretty = request.get("pretty", False)

                device_data = self.connection_manager.get_device(serial)
                if device_data:
                    device = device_data["device"]
                    try:
                        hierarchy_xml = device.dump_hierarchy(
                            compressed=compressed, pretty=pretty
                        )
                        response = {"status": "success", "data": hierarchy_xml}
                    except Exception as e:
                        response = {
                            "status": "error",
                            "message": f"Failed to dump hierarchy: {str(e)}",
                        }

            elif command == "app_current":
                serial = request.get("serial")
                device_data = self.connection_manager.get_device(serial)
                if device_data:
                    device = device_data["device"]
                    try:
                        current_app = device.app_current()
                        response = {"status": "success", "data": current_app}
                    except Exception as e:
                        response = {"status": "error", "message": str(e)}

            elif command == "device_info":
                serial = request.get("serial")
                device_data = self.connection_manager.get_device(serial)
                if device_data:
                    device = device_data["device"]
                    try:
                        info = device.info
                        response = {"status": "success", "data": info}
                    except Exception as e:
                        response = {"status": "error", "message": str(e)}

            elif command == "screenshot":
                serial = request.get("serial")
                filepath = request.get("filepath")

                device_data = self.connection_manager.get_device(serial)
                if device_data:
                    device = device_data["device"]
                    try:
                        if filepath:
                            device.screenshot(filepath)
                            response = {"status": "success", "data": "saved"}
                        else:
                            img = device.screenshot()
                            buffer = io.BytesIO()
                            img.save(buffer, format="PNG")
                            img_bytes = buffer.getvalue()
                            img_b64 = base64.b64encode(img_bytes).decode("utf-8")
                            response = {"status": "success", "data": img_b64}
                    except Exception as e:
                        response = {
                            "status": "error",
                            "message": f"Screenshot failed: {str(e)}",
                        }

            elif command == "execute":
                serial = request.get("serial")
                action = request.get("action")
                params = request.get("params", {})

                device_data = self.connection_manager.get_device(serial)
                if device_data:
                    device = device_data["device"]

                    if action == "click":
                        device.click(**params)
                        response = {"status": "success"}
                    elif action == "swipe":
                        device.swipe(**params)
                        response = {"status": "success"}
                    elif action == "text":
                        device.set_text(**params)
                        response = {"status": "success"}
                    elif action == "app_start":
                        device.app_start(**params)
                        response = {"status": "success"}
                    elif action == "shell":
                        cmd = params.pop("command", None)
                        if cmd:
                            result = device.shell(cmd, **params)
                        else:
                            result = device.shell(**params)
                        response = {"status": "success", "data": result}

            elif command == "status":
                devices = self.connection_manager.devices
                status_info = {
                    "devices_count": len(devices),
                    "devices": list(devices.keys()),
                    "uptime": datetime.now().isoformat(),
                }
                response = {"status": "success", "data": status_info}

            elif command == "ping":
                response = {"status": "success", "data": "pong"}

            self._send_data(client_socket, response)
        except Exception as e:
            error_response = {"status": "error", "message": str(e)}
            try:
                self._send_data(client_socket, error_response)
            except:
                pass
        finally:
            client_socket.close()

    def stop(self):
        self.running = False
        if self.server_socket:
            self.server_socket.close()
        self.connection_manager.close_all_connections()


class DeviceConnectionClient:
    def __init__(self, host="localhost", port=9999, auto_start_service=True):
        self.host = host
        self.port = port
        self.auto_start_service = auto_start_service
        self._ensure_service_running()

    def _is_service_running(self):
        try:
            test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            test_socket.settimeout(1)
            result = test_socket.connect_ex((self.host, self.port))
            test_socket.close()

            if result == 0:
                request = {"command": "ping"}
                response = self._send_request(request, timeout=2)
                return response.get("status") == "success"
            return False
        except:
            return False

    def _start_service_background(self):
        print("Starting Device Connection Service in background...")
        script_path = os.path.abspath(__file__)
        subprocess.Popen(
            [sys.executable, script_path, "server"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        for i in range(10):
            time.sleep(1)
            if self._is_service_running():
                print("✔ Service started successfully")
                return True

        print("✗ Failed to start service")
        return False

    def _ensure_service_running(self):
        if not self._is_service_running():
            if self.auto_start_service:
                if not self._start_service_background():
                    print("⚠ Service not running. Start it manually with:")
                    print(f"  python3 {os.path.basename(__file__)} server")
            else:
                print("⚠ Service not running. Start it with:")
                print(f"  python3 {os.path.basename(__file__)} server")

    def _recv_all(self, sock, size):
        data = b""
        while len(data) < size:
            chunk = sock.recv(min(size - len(data), 8192))
            if not chunk:
                raise ConnectionError("Connection closed")
            data += chunk
        return data

    def _send_data(self, sock, data):
        serialized = pickle.dumps(data)
        size = struct.pack("!I", len(serialized))
        sock.sendall(size + serialized)

    def _recv_data(self, sock):
        size_data = self._recv_all(sock, 4)
        size = struct.unpack("!I", size_data)[0]
        data = self._recv_all(sock, size)
        return pickle.loads(data)

    def _send_request(self, request, timeout=30):
        try:
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket.settimeout(timeout)
            client_socket.connect((self.host, self.port))

            self._send_data(client_socket, request)
            response = self._recv_data(client_socket)

            client_socket.close()
            return response
        except socket.timeout:
            return {"status": "error", "message": "Request timeout"}
        except ConnectionRefusedError:
            return {"status": "error", "message": "Service not running"}
        except Exception as e:
            return {"status": "error", "message": f"Connection failed: {str(e)}"}

    def discover_devices(self, force_reconnect=False):
        request = {"command": "discover", "force_reconnect": force_reconnect}
        return self._send_request(request, timeout=60)

    def get_device_status(self, serial):
        request = {"command": "get_device", "serial": serial}
        return self._send_request(request)

    def dump_hierarchy(self, serial, compressed=False, pretty=False):
        request = {
            "command": "dump_hierarchy",
            "serial": serial,
            "compressed": compressed,
            "pretty": pretty,
        }
        return self._send_request(request)

    def get_app_current(self, serial):
        request = {"command": "app_current", "serial": serial}
        return self._send_request(request)

    def get_device_info(self, serial):
        request = {"command": "device_info", "serial": serial}
        return self._send_request(request)

    def take_screenshot(self, serial, filepath=None):
        request = {"command": "screenshot", "serial": serial, "filepath": filepath}
        return self._send_request(request, timeout=15)

    def execute_action(self, serial, action, **params):
        request = {
            "command": "execute",
            "serial": serial,
            "action": action,
            "params": params,
        }
        return self._send_request(request)

    def batch_execute(self, actions):
        request = {"command": "batch_execute", "actions": actions}
        return self._send_request(request, timeout=60)

    def get_service_status(self):
        request = {"command": "status"}
        return self._send_request(request)


def run_client_test():
    print("\n═════════════════════════════════════════════")
    print("Device Connection Client Test")
    print("═════════════════════════════════════════════")

    time.sleep(2)

    client = DeviceConnectionClient(auto_start_service=False)

    print("\n1. Checking service status...")
    status = client.get_service_status()
    if status.get("status") == "success":
        data = status.get("data", {})
        print(f"   ✔ Service is running")
        print(f"   • Connected devices: {data.get('devices_count', 0)}")
        print(f"   • Device serials: {', '.join(data.get('devices', [])) or 'None'}")
    else:
        print(f"   ✗ Service error: {status.get('message')}")
        return

    print(
        "\n2. Discovering devices (this may take up to 60 seconds for many devices)..."
    )
    result = client.discover_devices()
    if result.get("status") == "success":
        devices = result.get("data", {})
        if devices:
            print(f"   ✔ Found {len(devices)} device(s):")
            for serial, info in devices.items():
                print(
                    f"     • {serial}: {info.get('model')} (connected at {info.get('connected_at')})"
                )

            print("\n3. Testing UI dump...")
            first_device = list(devices.keys())[0]
            hierarchy_result = client.dump_hierarchy(first_device)
            if hierarchy_result.get("status") == "success":
                xml_data = hierarchy_result.get("data", "")
                print(f"   ✔ UI hierarchy dumped for {first_device}")
                print(f"     Size: {len(xml_data)} characters")
            else:
                print(
                    f"   ✗ Failed to dump hierarchy: {hierarchy_result.get('message')}"
                )

            print("\n4. Testing screenshot...")
            screenshot_result = client.take_screenshot(first_device)
            if screenshot_result.get("status") == "success":
                print(f"   ✔ Screenshot captured for {first_device}")
            else:
                print(
                    f"   ✗ Failed to take screenshot: {screenshot_result.get('message')}"
                )
        else:
            print("   ⚠ No devices found. Make sure devices are connected via USB/ADB")
    else:
        print(f"   ✗ Discovery failed: {result.get('message')}")

    print("\n═════════════════════════════════════════════\n")


def is_service_running(host="localhost", port=9999):
    try:
        test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        test_socket.settimeout(1)
        result = test_socket.connect_ex((host, port))
        test_socket.close()
        return result == 0
    except:
        return False


def run_both():
    print("Starting server and client in parallel...")

    port = 9999
    if is_service_running("localhost", port):
        print(f"Port {port} is already in use, trying port {port + 1}...")
        port = port + 1

    service = DeviceConnectionService(port=port)
    server_thread = threading.Thread(target=service.start, daemon=True)
    server_thread.start()

    time.sleep(2)

    print(f"Connecting to server on port {port}...")

    print("\n═════════════════════════════════════════════")
    print("Device Connection Client Test")
    print("═════════════════════════════════════════════")

    client = DeviceConnectionClient(port=port, auto_start_service=False)

    print("\n1. Checking service status...")
    status = client.get_service_status()
    if status.get("status") == "success":
        data = status.get("data", {})
        print(f"   ✔ Service is running")
        print(f"   • Connected devices: {data.get('devices_count', 0)}")
        print(f"   • Device serials: {', '.join(data.get('devices', [])) or 'None'}")
    else:
        print(f"   ✗ Service error: {status.get('message')}")
        return

    print(
        "\n2. Discovering devices (this may take up to 60 seconds for many devices)..."
    )
    result = client.discover_devices()
    if result.get("status") == "success":
        devices = result.get("data", {})
        if devices:
            print(f"   ✔ Found {len(devices)} device(s):")
            for serial, info in devices.items():
                print(
                    f"     • {serial}: {info.get('model')} (connected at {info.get('connected_at')})"
                )

            print("\n3. Testing UI dump...")
            first_device = list(devices.keys())[0]
            hierarchy_result = client.dump_hierarchy(first_device)
            if hierarchy_result.get("status") == "success":
                xml_data = hierarchy_result.get("data", "")
                print(f"   ✔ UI hierarchy dumped for {first_device}")
                print(f"     Size: {len(xml_data)} characters")
            else:
                print(
                    f"   ✗ Failed to dump hierarchy: {hierarchy_result.get('message')}"
                )

            print("\n4. Testing screenshot...")
            screenshot_result = client.take_screenshot(first_device)
            if screenshot_result.get("status") == "success":
                print(f"   ✔ Screenshot captured for {first_device}")
            else:
                print(
                    f"   ✗ Failed to take screenshot: {screenshot_result.get('message')}"
                )
        else:
            print("   ⚠ No devices found. Make sure devices are connected via USB/ADB")
    else:
        print(f"   ✗ Discovery failed: {result.get('message')}")

    print("\n═════════════════════════════════════════════")
    print(f"\nServer is running on port {port} in the background")
    print("Press Ctrl+C to stop the server and exit\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\nShutting down service...")
        service.stop()
        print("Service stopped")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "server":
            service = DeviceConnectionService()
            try:
                service.start()
            except KeyboardInterrupt:
                print("\n\nShutting down service...")
                service.stop()
                print("Service stopped")
        elif sys.argv[1] == "client":
            run_client_test()
        elif sys.argv[1] == "both":
            run_both()
        else:
            print(f"Unknown argument: {sys.argv[1]}")
            print("Usage:")
            print(
                f"  python3 {os.path.basename(__file__)}         - Run client test (start server if needed)"
            )
            print(
                f"  python3 {os.path.basename(__file__)} server  - Start server only (keeps running)"
            )
            print(
                f"  python3 {os.path.basename(__file__)} client  - Run client test only"
            )
            print(
                f"  python3 {os.path.basename(__file__)} both    - Run client test (start server if needed)"
            )
    else:
        run_both()
