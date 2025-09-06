#!/bin/bash

reset_samsung_device() {
    local device_path=$1
    local device_id=$(basename $device_path)

    echo "Resetting device: $device_id"

    if [ -e "/sys/bus/usb/drivers/usb/$device_id" ]; then
        echo $device_id > /sys/bus/usb/drivers/usb/unbind
        sleep 1
        echo $device_id > /sys/bus/usb/drivers/usb/bind
        echo "Device $device_id reset complete"
    else
        echo "Device $device_id not found in USB drivers"
    fi
}

reset_all_samsung_devices() {
    for device in /sys/bus/usb/devices/*; do
        if [ -f "$device/idVendor" ] && [ -f "$device/idProduct" ]; then
            vendor=$(cat "$device/idVendor")
            product=$(cat "$device/idProduct")

            if [ "$vendor" = "04e8" ] && [ "$product" = "6860" ]; then
                device_id=$(basename "$device")
                reset_samsung_device "$device"
                sleep 2
            fi
        fi
    done
}

reset_specific_device() {
    local bus=$1
    local device=$2

    for path in /sys/bus/usb/devices/*; do
        if [ -f "$path/busnum" ] && [ -f "$path/devnum" ]; then
            busnum=$(cat "$path/busnum")
            devnum=$(cat "$path/devnum")

            if [ "$busnum" -eq "$bus" ] && [ "$devnum" -eq "$device" ]; then
                device_id=$(basename "$path")
                reset_samsung_device "$path"
                return 0
            fi
        fi
    done

    echo "Device not found at Bus $bus Device $device"
    return 1
}

reset_by_port() {
    local hub_device=$1
    local port=$2

    authorized_path="/sys/bus/usb/devices/$hub_device/$hub_device.$port/authorized"

    if [ -f "$authorized_path" ]; then
        echo 0 > "$authorized_path"
        sleep 1
        echo 1 > "$authorized_path"
        echo "Port $port on hub $hub_device reset"
    else
        echo "Port path not found: $authorized_path"
    fi
}

list_samsung_devices() {
    echo "Samsung devices found:"
    echo "======================"

    for device in /sys/bus/usb/devices/*; do
        if [ -f "$device/idVendor" ] && [ -f "$device/idProduct" ]; then
            vendor=$(cat "$device/idVendor")
            product=$(cat "$device/idProduct")

            if [ "$vendor" = "04e8" ] && [ "$product" = "6860" ]; then
                device_id=$(basename "$device")
                busnum=$(cat "$device/busnum" 2>/dev/null || echo "N/A")
                devnum=$(cat "$device/devnum" 2>/dev/null || echo "N/A")

                echo "Device ID: $device_id, Bus: $busnum, Device: $devnum"
            fi
        fi
    done
}

case "$1" in
    all)
        echo "Resetting all Samsung .."
        reset_all_samsung_devices
        ;;
    device)
        if [ $# -ne 3 ]; then
            echo "Usage: $0 device <bus_number> <device_number>"
            echo "Example: $0 device 9 126"
            exit 1
        fi
        reset_specific_device $2 $3
        ;;
    port)
        if [ $# -ne 3 ]; then
            echo "Usage: $0 port <hub_device_id> <port_number>"
            echo "Example: $0 port 1-3.1 4"
            exit 1
        fi
        reset_by_port $2 $3
        ;;
    list)
        list_samsung_devices
        ;;
    *)
        echo "USB Samsung Device Reset Tool"
        echo "=============================="
        echo ""
        echo "Usage:"
        echo "  $0 all                    - Reset all Samsung devices"
        echo "  $0 device <bus> <dev>     - Reset specific device by bus and device number"
        echo "  $0 port <hub_id> <port>   - Reset device on specific hub port"
        echo "  $0 list                   - List all Samsung devices"
        echo ""
        echo "Example:"
        echo "  $0 all"
        echo "  $0 device 9 126"
        echo "  $0 port 1-3.1.4 3"
        echo ""
        echo "Note: Run with sudo for permission to reset devices"
        ;;
esac
