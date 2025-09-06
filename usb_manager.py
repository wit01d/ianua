import logging
import subprocess
import time
from typing import Dict, List, Optional

import usb.core
import usb.util


class USBManager:
    ANDROID_VENDOR_IDS = [
        0x18d1,
        0x0bb4,
        0x04e8,
        0x22b8,
        0x1004,
        0x12d1,
        0x0502,
        0x0fce,
        0x19d2,
        0x04dd,
        0x0930,
        0x05c6,
        0x2717,
        0x0414,
        0x2a70,
        0x1f3a,
    ]

    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger(__name__)
        self.known_devices = {}

    def find_android_devices(self) -> List[Dict]:
        android_devices = []

        try:
            for vendor_id in self.ANDROID_VENDOR_IDS:
                devices = usb.core.find(find_all=True, idVendor=vendor_id)
                for device in devices:
                    try:
                        device_info = self._get_device_info(device)
                        if device_info:
                            android_devices.append(device_info)
                    except Exception as e:
                        self.logger.debug(f"Failed to get info for USB device: {e}")
        except Exception as e:
            self.logger.error(f"Error finding Android USB devices: {e}")

        return android_devices

    def _get_device_info(self, device) -> Optional[Dict]:
        try:
            info = {
                'vendor_id': hex(device.idVendor),
                'product_id': hex(device.idProduct),
                'bus': device.bus,
                'address': device.address,
                'port': f"{device.bus}-{device.address}"
            }

            try:
                info['manufacturer'] = usb.util.get_string(device, device.iManufacturer)
            except:
                info['manufacturer'] = 'Unknown'

            try:
                info['product'] = usb.util.get_string(device, device.iProduct)
            except:
                info['product'] = 'Unknown'

            try:
                info['serial'] = usb.util.get_string(device, device.iSerialNumber)
            except:
                info['serial'] = None

            return info
        except Exception as e:
            self.logger.debug(f"Failed to get USB device info: {e}")
            return None

    def reset_usb_device_by_serial(self, serial: str) -> bool:
        usb_devices = self.find_android_devices()

        for usb_device in usb_devices:
            if usb_device.get('serial') == serial:
                return self._reset_usb_by_port(usb_device['vendor_id'],
                                              usb_device['product_id'])

        self.logger.warning(f"USB device with serial {serial} not found")
        return False

    def _reset_usb_by_port(self, vendor_id: str, product_id: str) -> bool:
        try:
            vendor_id_int = int(vendor_id, 16)
            product_id_int = int(product_id, 16)

            device = usb.core.find(idVendor=vendor_id_int, idProduct=product_id_int)
            if device:
                try:
                    device.reset()
                    self.logger.info(f"Reset USB device {vendor_id}:{product_id}")
                    time.sleep(3)
                    return True
                except usb.core.USBError as e:
                    if e.errno == 13:
                        self.logger.warning("Permission denied for USB reset. Try running with sudo.")
                    else:
                        self.logger.error(f"USB reset failed: {e}")
        except Exception as e:
            self.logger.error(f"Failed to reset USB device: {e}")

        return False

    def unbind_bind_usb(self, vendor_id: str, product_id: str) -> bool:
        try:
            result = subprocess.run(
                ['lsusb', '-d', f'{vendor_id}:{product_id}'],
                capture_output=True, text=True
            )

            if result.returncode != 0:
                return False

            output = result.stdout.strip()
            if not output:
                return False

            parts = output.split()
            bus = parts[1]
            device = parts[3].rstrip(':')

            usb_path = f"/sys/bus/usb/devices/{bus}-{device}"

            try:
                with open(f"{usb_path}/driver/unbind", 'w') as f:
                    f.write(f"{bus}-{device}")
                time.sleep(1)

                with open(f"{usb_path}/driver/bind", 'w') as f:
                    f.write(f"{bus}-{device}")
                time.sleep(2)

                self.logger.info(f"Successfully unbound and rebound USB device {vendor_id}:{product_id}")
                return True

            except PermissionError:
                self.logger.warning("Permission denied for USB unbind/bind. Root access required.")
                return False

        except Exception as e:
            self.logger.error(f"Failed to unbind/bind USB device: {e}")
            return False

    def monitor_usb_changes(self, callback):
        previous_devices = set()

        while True:
            try:
                current_devices = set()
                android_devices = self.find_android_devices()

                for device in android_devices:
                    device_id = f"{device['vendor_id']}:{device['product_id']}:{device.get('serial', 'unknown')}"
                    current_devices.add(device_id)

                new_devices = current_devices - previous_devices
                removed_devices = previous_devices - current_devices

                if new_devices:
                    for device_id in new_devices:
                        self.logger.info(f"New USB device detected: {device_id}")
                        if callback:
                            callback('connected', device_id)

                if removed_devices:
                    for device_id in removed_devices:
                        self.logger.info(f"USB device removed: {device_id}")
                        if callback:
                            callback('disconnected', device_id)

                previous_devices = current_devices

            except Exception as e:
                self.logger.error(f"Error monitoring USB changes: {e}")

            time.sleep(2)
