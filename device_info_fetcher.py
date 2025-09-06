#!/usr/bin/env python3

import logging
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

sys.path.append(str(Path.home() / "projects" / "ianua"))

from config import ADB_CONFIG, DB_CONFIG, Device, DeviceStatus

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class AndroidDeviceFetcher:
    def __init__(self):
        database_url = (
            f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}"
            f"@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}"
        )
        self.engine = create_engine(database_url)
        self.Session = sessionmaker(bind=self.engine)

    def run_adb_command(self, command: List[str], timeout: int = 10) -> Optional[str]:
        try:
            result = subprocess.run(
                ["adb"] + command, capture_output=True, text=True, timeout=timeout
            )
            if result.returncode == 0:
                return result.stdout.strip()
            else:
                logger.error(f"ADB command failed: {result.stderr}")
                return None
        except subprocess.TimeoutExpired:
            logger.error(f"ADB command timed out: {command}")
            return None
        except Exception as e:
            logger.error(f"Error running ADB command: {e}")
            return None

    def get_device_list(self) -> List[Dict[str, str]]:
        devices = []
        output = self.run_adb_command(["devices", "-l"])

        if not output:
            return devices

        for line in output.split("\n")[1:]:
            if not line.strip():
                continue

            parts = line.split()
            if len(parts) >= 2:
                device_info = {"serial": parts[0], "status": parts[1]}

                for part in parts[2:]:
                    if ":" in part:
                        key, value = part.split(":", 1)
                        device_info[key] = value

                devices.append(device_info)

        return devices

    def get_device_property(self, serial: str, prop: str) -> Optional[str]:
        output = self.run_adb_command(["-s", serial, "shell", "getprop", prop])
        return output.strip() if output else None

    def get_device_details(self, serial: str) -> Dict[str, any]:
        details = {"serial_number": serial, "status": DeviceStatus.ONLINE}

        properties = {
            "model": "ro.product.model",
            "manufacturer": "ro.product.manufacturer",
            "android_version": "ro.build.version.release",
            "sdk_version": "ro.build.version.sdk",
            "product": "ro.product.name",
            "device_name": "ro.product.device",
        }

        for key, prop in properties.items():
            value = self.get_device_property(serial, prop)
            if value:
                if key == "sdk_version":
                    try:
                        details[key] = int(value)
                    except ValueError:
                        details[key] = None
                else:
                    details[key] = value

        transport_output = self.run_adb_command(["-s", serial, "get-state"])
        if transport_output:
            details["status"] = DeviceStatus.ONLINE
        else:
            details["status"] = DeviceStatus.OFFLINE

        return details

    def update_device_in_db(self, device_data: Dict[str, any]):
        session = self.Session()
        try:
            existing_device = (
                session.query(Device)
                .filter_by(serial_number=device_data["serial_number"])
                .first()
            )

            if existing_device:
                for key, value in device_data.items():
                    if value is not None:
                        setattr(existing_device, key, value)
                existing_device.updated_at = datetime.now(timezone.utc)
                logger.info(f"Updated device: {device_data['serial_number']}")
            else:
                new_device = Device(**device_data)
                session.add(new_device)
                logger.info(f"Added new device: {device_data['serial_number']}")

            session.commit()

        except IntegrityError as e:
            session.rollback()
            logger.error(f"Database integrity error: {e}")
        except Exception as e:
            session.rollback()
            logger.error(f"Error updating database: {e}")
        finally:
            session.close()

    def mark_offline_devices(self, online_serials: List[str]):
        session = self.Session()
        try:
            offline_devices = (
                session.query(Device)
                .filter(
                    Device.serial_number.notin_(online_serials),
                    Device.status != DeviceStatus.OFFLINE,
                )
                .all()
            )

            for device in offline_devices:
                device.status = DeviceStatus.OFFLINE
                device.updated_at = datetime.now(timezone.utc)
                logger.info(f"Marked device offline: {device.serial_number}")

            session.commit()

        except Exception as e:
            session.rollback()
            logger.error(f"Error marking devices offline: {e}")
        finally:
            session.close()

    def fetch_and_update_devices(self):
        logger.info("Starting device fetch...")

        self.run_adb_command(["start-server"])

        devices = self.get_device_list()
        online_serials = []

        for device in devices:
            serial = device.get("serial")
            status = device.get("status")

            if not serial:
                continue

            if status == "device":
                logger.info(f"Fetching details for device: {serial}")
                device_details = self.get_device_details(serial)

                if device.get("usb"):
                    device_details["usb_port"] = device.get("usb")
                if device.get("transport_id"):
                    device_details["transport_id"] = device.get("transport_id")

                self.update_device_in_db(device_details)
                online_serials.append(serial)

            elif status == "unauthorized":
                logger.warning(f"Device unauthorized: {serial}")
                self.update_device_in_db(
                    {"serial_number": serial, "status": DeviceStatus.UNAUTHORIZED}
                )
            elif status == "offline":
                logger.warning(f"Device offline: {serial}")
                self.update_device_in_db(
                    {"serial_number": serial, "status": DeviceStatus.OFFLINE}
                )

        self.mark_offline_devices(online_serials)
        logger.info(
            f"Device fetch completed. Found {len(online_serials)} online devices."
        )


def main():
    fetcher = AndroidDeviceFetcher()
    fetcher.fetch_and_update_devices()
    fetcher.engine.dispose()


if __name__ == "__main__":
    main()
