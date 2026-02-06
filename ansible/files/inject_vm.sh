#!/bin/bash
VMID=9000

function push_file() {
    SRC=$1
    DEST=$2
    echo "Pushing $SRC to $DEST..."

    # Initialize file
    qm guest exec $VMID cmd -- /c "echo. > $DEST"

    # Append lines
    while IFS= read -r line; do
        # Skip empty lines to speed up
        if [ ! -z "$line" ]; then
           # Escape single quotes for Powershell
           ESCAPED_LINE=$(echo "$line" | sed "s/'/''/g")
           qm guest exec $VMID powershell -- -Command "Add-Content -Path '$DEST' -Value '$ESCAPED_LINE'" >/dev/null
        fi
    done < "$SRC"
}

push_file "/tmp/squid-ca.pem" "C:\\squid-ca.pem"
push_file "/tmp/enable_winrm.ps1" "C:\\enable_winrm.ps1"
