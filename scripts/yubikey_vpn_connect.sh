#!/bin/bash
### You will need ykman (yubikey manager), openconnect (anyconnect alternative), and op (1password CLI) installed
### You will need these two lines in your sudoers file
# %admin ALL=(ALL) NOPASSWD: /opt/homebrew/bin/openconnect
# %admin ALL=(ALL) NOPASSWD: /usr/bin/pkill openconnect
### Finally if you want this to be a daemon you'll need a file in ~/Library/LaunchAgents/com.example.vpn_yubikey.plist with this content
# <?xml version="1.0" encoding="UTF-8"?>
# <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
# <plist version="1.0">
# <dict>
#     <key>Label</key>
#     <string>com.example.vpn_yubikey</string>
#     <key>ProgramArguments</key>
#     <array>
#         <string>/usr/local/bin/yubikey_vpn_connect</string>
#     </array>
#     <key>RunAtLoad</key>
#     <true/>
#     <key>KeepAlive</key>
#     <true/>
#     <key>StandardOutPath</key>
#     <string>/Users/adam.durham/Library/Logs/vpn_yubikey.log</string>
#     <key>StandardErrorPath</key>
#     <string>/Users/adam.durham/Library/Logs/vpn_yubikey.log</string>
# </dict>
# </plist>

# YubiKey serial number to check for
YUBIKEY_SERIAL="REDACTED"
# Server to connect to
VPN_SERVER="REDACTED"
# Group to auth with
VPN_GROUP="REDACTED"
# Name of the item in 1Password
OP_ITEM_NAME="REDACTED"

# Paths to ykman, openconnect, and op
YKMAN_PATH="/opt/homebrew/bin/ykman"
OPENCONNECT_PATH="/opt/homebrew/bin/openconnect"
OP_PATH="/opt/homebrew/bin/op"

# Initialize previous states
prev_yubikey_state="unknown"
prev_vpn_state="unknown"
vpn_interface=""

# Function to check if YubiKey is inserted
check_yubikey() {
    $YKMAN_PATH list | grep -q "$YUBIKEY_SERIAL"
    return $?
}

# Function to get the list of network interfaces
get_interfaces() {
    ifconfig | grep -Eo 'utun[0-9]+'
}

# Function to check if VPN is connected
is_vpn_connected() {
    for iface in $(get_interfaces); do
        if ifconfig "$iface" | grep -q "inet "; then
            vpn_interface="$iface"
            return 0
        fi
    done
    return 1
}

# Function to disconnect from VPN
disconnect_vpn() {
    sudo pkill openconnect
    vpn_interface=""
}

# Function to get VPN username and password from 1Password
get_vpn_credentials() {
    $OP_PATH item get "$OP_ITEM_NAME" |
    awk '/Fields:/ {f=1} f && /username:/ {sub(/@.*$/, "", $2); username=$2} f && /password:/ {password=$2; exit} END {print username, password}'
}

# Function to wait until the VPN connection is fully established
wait_for_vpn_connection() {
    while ! is_vpn_connected; do
        sleep 1
    done
}

# Function to handle the state change of YubiKey
handle_yubikey_state_change() {
    check_yubikey
    current_yubikey_state=$?
    is_vpn_connected
    current_vpn_state=$?

    if [ $current_yubikey_state -ne 0 ]; then
        if [ $current_vpn_state -eq 0 ]; then
            echo "YubiKey not detected. VPN connected. Disconnecting..."
            disconnect_vpn
        fi
    else
        if [ $current_vpn_state -ne 0 ]; then
            credentials=$(get_vpn_credentials)
            IFS=' ' read -r username password <<< "$credentials"
            echo "YubiKey detected. VPN not connected. Connecting..."
            sudo $OPENCONNECT_PATH --user="$username" --authgroup="$VPN_GROUP" --passwd-on-stdin --non-inter "$VPN_SERVER" <<<"$password" >/dev/null 2>&1 &
            wait_for_vpn_connection
            echo "YubiKey detected. VPN connected."
        fi
    fi

    # Update previous states
    prev_yubikey_state=$([ $current_yubikey_state -eq 0 ] && echo "true" || echo "false")
    prev_vpn_state=$([ $current_vpn_state -eq 0 ] && echo "true" || echo "false")
}

# Function to print the initial state on startup
print_initial_state() {
    check_yubikey
    if [ $? -eq 0 ]; then
        yubikey_state="YubiKey detected"
    else
        yubikey_state="YubiKey not detected"
    fi

    if is_vpn_connected; then
        vpn_state="VPN connected"
    else
        vpn_state="VPN not connected"
    fi

    echo "$yubikey_state. $vpn_state."
}

# Continuously monitor USB device changes using system_profiler
monitor_usb_events() {
    print_initial_state
    while true; do
        handle_yubikey_state_change
        sleep 1
    done
}

# Start monitoring USB events
monitor_usb_events
