#!/bin/bash
VMID=9002
# Inject to C:\Root to assume fewer permission/path issues
DEST="C:\\Unattend.xml"

# Create File
qm guest exec $VMID cmd -- /c "echo. > $DEST"

# Read local file and append
while IFS= read -r line; do
    if [ ! -z "$line" ]; then
        ESCAPED_LINE=$(echo "$line" | sed "s/'/''/g")
        qm guest exec $VMID powershell -- -Command "Add-Content -Path '$DEST' -Value '$ESCAPED_LINE'" >/dev/null
    fi
done < "/tmp/Unattend.xml"

qm guest exec $VMID cmd -- /c "dir $DEST"
