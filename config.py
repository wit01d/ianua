#!/usr/bin/env python3

import enum
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    Integer,
    String,
)
from sqlalchemy.ext.declarative import declarative_base

PROJECT_DIR = Path.home() / "projects" / "ianua"
VENV_DIR = PROJECT_DIR / ".venv"

load_dotenv(PROJECT_DIR / ".env")

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'database': os.getenv('DB_NAME', 'ianua'),
    'user': os.getenv('DB_USER', 'dbw'),
    'password': os.getenv('DB_PASSWORD', '123'),
    'port': int(os.getenv('DB_PORT', 5432))
}

ADB_CONFIG = {
    'adb_key_path': os.path.expanduser("~/.android/adbkey"),
    'timeout': 10,
    'retry_count': 3,
    'reconnect_delay': 2
}

USB_CONFIG = {
    'android_vendor_ids': [
        0x18d1, 0x0bb4, 0x04e8, 0x22b8, 0x1004, 0x12d1,
        0x0502, 0x0fce, 0x19d2, 0x04dd, 0x0930, 0x05c6,
        0x2717, 0x0414, 0x2a70, 0x1f3a
    ],
    'scan_interval': 2
}


Base = declarative_base()

class DeviceStatus(enum.Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    UNAUTHORIZED = "unauthorized"
    CONNECTING = "connecting"
    ERROR = "error"


class Device(Base):
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    serial_number = Column(String(100), unique=True, nullable=False, index=True)
    model = Column(String(100))
    manufacturer = Column(String(100))
    android_version = Column(String(50))
    sdk_version = Column(Integer)
    product = Column(String(100))
    device_name = Column(String(100))
    transport_id = Column(String(50))
    usb_port = Column(String(50))
    status = Column(Enum(DeviceStatus), default=DeviceStatus.OFFLINE)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
